import typing

from sqlalchemy import update, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.expression import func

from alws import models

from alws.errors import UserError, PermissionDenied
from alws.perms import actions
from alws.perms.authorization import can_perform
from alws.schemas import user_schema


async def get_user(
            db: AsyncSession,
            user_id: typing.Optional[int] = None,
            user_name: typing.Optional[str] = None,
            user_email: typing.Optional[str] = None
        ) -> models.User:
    query = select(models.User).options(
        selectinload(models.User.roles).selectinload(models.UserRole.actions),
        selectinload(models.User.teams)
    )
    condition = models.User.id == user_id
    if user_name is not None:
        condition = models.User.name == user_name
    elif user_email is not None:
        condition = models.User.email == user_email
    db_user = await db.execute(query.where(condition))
    return db_user.scalars().first()


async def get_all_users(db: AsyncSession) -> typing.List[models.User]:
    db_users = await db.execute(select(models.User).options(
        selectinload(models.User.oauth_accounts)))
    return db_users.scalars().all()


async def activate_user(user_id: int, db: AsyncSession):
    await db.execute(update(models.User).where(
        models.User.id == user_id).values(is_verified=True, is_active=True))


async def deactivate_user(user_id: int, db: AsyncSession):
    await db.execute(update(models.User).where(
        models.User.id == user_id).values(is_verified=False, is_active=False))


async def make_superuser(user_id: int, db: AsyncSession):
    await db.execute(update(models.User).where(
        models.User.id == user_id).values(is_superuser=True))


async def make_usual_user(user_id: int, db: AsyncSession):
    await db.execute(update(models.User).where(
        models.User.id == user_id).values(is_superuser=False))


async def check_valuable_artifacts(user_id: int, db: AsyncSession):
    # Check that the user doesn't own valuable artifacts
    # Related and potential valuable artifacts are:
    #   - build_releases where owner_id == user_id
    #   - builds where owner_id == user_id and released == true
    #   - other users have builds from the user linked in their builds
    #   - platform_flavours where owner_id == user_id
    #   - platforms where owner_id == user_id
    #   - products where owner_id == user_id
    #   - repositories where owner_id == user_id and production == true
    #   - sign_keys where owner_id == user_id?
    #   - teams where owner_id == user_id and
    #     if count(*) from products where team_id in
    #         (select id from teams where owner_id=user_id)?
    #
    # For now, we try to remove and if there are any linked artifacts to this user id
    # we will just fail and return a generic error.
    # TODO: Maybe add more fine grained checks?
    user_artifacts = {}
    build_releases = (await db.execute(
        select(func.count()).select_from(models.Release).where(
          models.Release.owner_id == user_id
        )
    )).scalar()
    user_artifacts['build_releases'] = build_releases

    # TODO - Double check: If a build is signed and released, does it
    # mean it's also taken into account in the previous check?
    released_builds = (await db.execute(
        select(models.Build.id).where(
          models.Build.owner_id == user_id,
          or_(models.Build.released == True, models.Build.signed == True)
        )
    )).scalars().all()
    user_artifacts['released_builds'] = len(released_builds)

    # Check if other users have linked builds from this user
    build_ids = (await db.execute(
        select(models.Build.id).where(
          models.Build.owner_id == user_id
        )
    )).scalars().all()

    # Search all build_ids that have any of the user's build_ids
    # as a build dependency
    dependent_build_ids = (await db.execute(
        select(models.BuildDependency).where(
            models.BuildDependency.c.build_dependency.in_(tuple(build_ids)))
    )).scalars().all()

    # If any dependent_build_id depends on any the user's builds,
    # and if they are not owned by the user, then, we can tell that
    # another user has linked a build from the user to delete, hence
    # we will not continue delete the user
    if dependent_build_ids:
        other_user_build_ids = [
            build_id for build_id in dependent_build_ids
            if build_id not in build_ids
        ]
        if other_user_build_ids:
            user_artifacts['linked_builds'] = len(other_user_build_ids)

    platforms = (await db.execute(
        select(func.count()).select_from(models.Platform).where(
          models.Platform.owner_id == user_id
        )
    )).scalar()
    user_artifacts['platforms'] = platforms

    products = (await db.execute(
        select(func.count()).select_from(models.Product).where(
          models.Product.owner_id == user_id
        )
    )).scalar()
    user_artifacts['products'] = products

    repositories = (await db.execute(
        select(func.count()).select_from(models.Repository).where(
          models.Repository.owner_id == user_id,
          models.Repository.production == True
        )
    )).scalar()
    user_artifacts['repositories'] = repositories

    sign_keys = (await db.execute(
        select(func.count()).select_from(models.SignKey).where(
          models.SignKey.owner_id == user_id
        )
    )).scalar()
    user_artifacts['sign_keys'] = sign_keys

    teams = (await db.execute(
        select(func.count()).select_from(models.Team).where(
          models.Team.owner_id == user_id
        )
    )).scalar()
    user_artifacts['teams'] = teams

    # TODO: Maybe remove if the user is not manager?
    user = (await db.execute(
        select(models.User).where(
          models.User.id == user_id
        ).options(
          selectinload(models.User.teams)
        )
    )).scalars().first()
    if user.teams: user_artifacts['team_membership'] = len(user.teams)

    valuable_artifacts = [
            artifact for artifact
            in user_artifacts
            if user_artifacts[artifact]>=1
    ]
    return valuable_artifacts


async def remove_user(user_id: int, db: AsyncSession):
    async with db.begin():
        user = await get_user(db, user_id=user_id)
        if not user:
            raise UserError(f'User with ID {user_id} does not exist')
        valuable_artifacts = await check_valuable_artifacts(user_id, db)

    if valuable_artifacts:
        err = f"Can't delete the user {user.username} because he/she "
        errors = []
        # Maybe we should get rid of this concatenation of error message
        # and treat team_membership as the other valuable_artifacts
        if ('team_membership' in valuable_artifacts):
            valuable_artifacts.remove('team_membership')
            errors.append('is a member of one or several teams')
        if valuable_artifacts:
            errors.append(
                f'owns some valuable artifacts ({", ".join(valuable_artifacts)})')

        if len(errors) == 2:
            err = err + " and ".join(errors)
        else:
            err = err + "".join(errors)
        raise UserError(err)
    else:
        # ALBS-620: When removing a user with a considerable
        # amount of builds, this might take some time.
        # For this reason, we are queuing the user removal process
        from alws.dramatiq import perform_user_removal
        perform_user_removal.send(user_id)


async def update_user(
        db: AsyncSession, user_id: int,
        payload: user_schema.UserUpdate):
    user = await get_user(db, user_id=user_id)
    if not user:
        raise UserError(f'User with ID {user_id} does not exist')
    for k, v in payload.dict().items():
        if v!= None: setattr(user, k, v)
    db.add(user)
    await db.commit()
    await db.refresh(user)


async def get_user_roles(db: AsyncSession, user_id: int):
    async with db.begin():
        user = (await db.execute(
            select(models.User).where(
                models.User.id == user_id
            ).options(
                selectinload(models.User.roles)
            )
        )).scalars().first()
    if not user:
        raise UserError(f'User with ID {user_id} does not exist')

    return user.roles

async def can_edit_teams_roles(db: AsyncSession,
                               roles_ids: typing.List[int],
                               user_id: int):
    user = await get_user(db, user_id)
    teams_ids = (await db.execute(select(models.TeamRoleMapping.c.team_id).where(
        models.TeamRoleMapping.c.role_id.in_(roles_ids)).distinct(
            models.TeamRoleMapping.c.team_id)
    )).scalars().all()
    for team_id in teams_ids:
        team = (await db.execute(select(models.Team).where(
            models.Team.id == team_id).options(
                selectinload(models.Team.roles).selectinload(models.UserRole.actions),
                selectinload(models.Team.owner)
            )
        )).scalars().first()

        if not can_perform(team, user, actions.AssignTeamRole.name):
            return False
    return True



async def add_roles(db: AsyncSession, user_id: int,
                    roles_ids: typing.List[int],
                    current_user_id: int):
    async with db.begin():
        user = await get_user(db, user_id)

        if not await can_edit_teams_roles(db, roles_ids, current_user_id):
            raise PermissionDenied("The user has no permissions to edit teams user roles")

        add_roles = (await db.execute(select(models.UserRole).where(
            models.UserRole.id.in_(roles_ids))
        )).scalars().all()
        user.roles.extend(add_roles)
        db.add(user)


async def remove_roles(db: AsyncSession, user_id: int,
                       roles_ids: typing.List[int],
                       current_user_id: int):
    async with db.begin():
        user = await get_user(db, user_id)

        if not await can_edit_teams_roles(db, roles_ids, current_user_id):
            raise PermissionDenied("The user has no permissions to edit teams user roles")

        await db.execute(delete(models.UserRoleMapping).where(
            models.UserRoleMapping.c.role_id.in_(roles_ids),
            models.UserRoleMapping.c.user_id == user_id
        ))


async def get_user_teams(db: AsyncSession, user_id: int):
    async with db.begin():
        user = (await db.execute(
            select(models.User).where(
                models.User.id == user_id
            ).options(
                selectinload(models.User.teams)
            )
        )).scalars().first()
    response = [{'id': team.id, 'name': team.name} for team in user.teams]
    return response
