import asyncio
import dramatiq
import pprint
import typing

from collections import defaultdict
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from alws import models
from alws.config import settings
from alws.constants import BuildTaskStatus, DRAMATIQ_TASK_TIMEOUT
from alws.database import Session
from alws.dramatiq import event_loop
from alws.utils.log_utils import setup_logger
from alws.utils.pulp_client import PulpClient

__all__ = ['perform_product_modification']

logger = setup_logger(__name__)

async def get_existing_packages(
    pulp_client: PulpClient,
    repository: models.Repository,
) -> typing.List[typing.Dict[str, str]]:

    pulp_fields = ["pulp_href", "artifact", "sha256", "location_href", "arch"]
    return await pulp_client.get_rpm_repository_packages(
        repository.pulp_href,
        include_fields=pulp_fields,
    )


async def get_packages(
    pulp_client: PulpClient,
    build_repo: models.Repository,
    dist_repo: models.Repository,
    modification: str,
    pkgs_blacklist: typing.List[str]
) -> typing.Tuple[str, typing.List[str]]:

    def filter_by_arch(pkgs: typing.List[dict], repo_arch: str):
        filtered = []
        for pkg in pkgs:
            if pkg["arch"] == "noarch" and repo_arch != "src":
                filtered.append(pkg)
            elif pkg["arch"] == "i686" and repo_arch in ("i686", "x86_64"):
                filtered.append(pkg)
            elif pkg["arch"] == repo_arch:
                filtered.append(pkg)
        return filtered

    dist_packages = await get_existing_packages(pulp_client, dist_repo)
    search_by_href = set([pkg["pulp_href"] for pkg in dist_packages])
    build_packages = await get_existing_packages(pulp_client, build_repo)
    filtered_build_packages = filter_by_arch(build_packages, dist_repo.arch)
    logger.debug("Packages in product repository %s:\n%s", dist_repo.name,
                 pprint.pformat(dist_packages))
    logger.debug("Set of packages HREFs for comparison "
                 "with build artifacts:\n%s",
                 pprint.pformat(search_by_href))
    logger.debug("List of build packages in build repository %s:\n%s",
                 build_repo.name, pprint.pformat(filtered_build_packages))
    if modification == "add":
        dedup_mapping = {}
        for pkg in filtered_build_packages:
            if pkg["location_href"] in dedup_mapping or \
                pkg["pulp_href"] in pkgs_blacklist:
                continue
            dedup_mapping[pkg["location_href"]] = pkg["pulp_href"]
        logger.debug("Deduplication mapping for packages"
                     "with the same name:\n%s", pprint.pformat(dedup_mapping))
        final_packages = [
            href for href in dedup_mapping.values()
            if href not in search_by_href
        ]
    else:
        final_packages = [
            pkg["pulp_href"] for pkg in filtered_build_packages
            if pkg["pulp_href"] in search_by_href
        ]
    logger.debug("Final list of packages to %s:\n%s", modification,
                 pprint.pformat(final_packages))
    return dist_repo.pulp_href, final_packages


async def prepare_repo_modify_dict(
    db_build: models.Build,
    db_product: models.Product,
    pulp_client: PulpClient,
    modification: str,
    pkgs_blacklist: typing.List[str]
) -> typing.Dict[str, typing.List[str]]:

    product_repo_mapping = {(repo.arch, repo.debug, repo.platform.name): repo
                            for repo in db_product.repositories}
    modify = defaultdict(list)
    build_repos = [repo for repo in db_build.repos if repo.type == "rpm"]
    tasks = []
    for repo in build_repos:
        dist_repo = product_repo_mapping.get(
            (repo.arch, repo.debug, repo.platform.name)
        )
        if dist_repo is None:
            continue
        tasks.append(get_packages(
            pulp_client, repo, dist_repo, modification, pkgs_blacklist
        ))

    results = await asyncio.gather(*tasks)
    modify.update(**dict(results))

    for task in db_build.tasks:
        if task.status != BuildTaskStatus.COMPLETED:
            continue
        if task.rpm_module:
            product_repo = product_repo_mapping.get(
                (task.arch, False, task.platform.name)
            )
            if product_repo is None:
                continue
            modify[product_repo.pulp_href].append(task.rpm_module.pulp_href)

    return modify


async def set_platform_for_products_repos(
    db: Session,
    product: models.Product,
) -> None:
    repo_debug_dict = {
        True: "debug-dr",
        False: "dr",
    }
    # name of a product's repo:
    # some-username-some-product-some-platform-x86_64-debug-dr
    repos_per_platform = {
        f"{product.owner.username}-{product.name}-{platform.name.lower()}-"
        f"{repo.arch}-{repo_debug_dict[repo.debug]}": platform
        for repo in product.repositories for platform in product.platforms
    }
    # we do nothing if all repos have platform
    if all(repo.platform for repo in product.repositories):
        return
    for repo in product.repositories:
        repo.platform = repos_per_platform[repo.name]


async def set_platform_for_build_repos(
    db: Session,
    build: models.Build,
) -> None:
    repo_debug_dict = {
        True: "debug-br",
        False: "br",
    }
    # name of a build's repo:
    # some-platform-x86_64-some-build-id-debug-br
    repos_per_platform = {
        f"{task.platform.name}-{repo.arch}-{build.id}-"
        f"{repo_debug_dict[repo.debug]}": task.platform
        for repo in build.repos for task in build.tasks
    }
    # we do nothing if all repos have platform
    if all(repo.platform for repo in build.repos):
        return
    for repo in build.repos:
        if repo.type != "rpm":
            continue
        repo.platform = repos_per_platform[repo.name]


def group_tasks_by_ref_id(
    build_tasks: typing.List[models.BuildTask]
) -> dict:
    tasks_by_ref = defaultdict(list)
    {
        tasks_by_ref[task_ref].append(
            (
                task_id, task_status
            )
        )
        for (
            task_ref,
            task_id,
            task_status
        )
        in [
            (
                task.ref_id,
                task.id,
                (task.status == BuildTaskStatus.COMPLETED)
            )
            for task in build_tasks
        ]
    }
    return tasks_by_ref


async def get_packages_to_blacklist(
    db: Session,
    build_tasks: typing.List[models.BuildTask]
) -> typing.List:

    # We should skip src.rpms coming from failed tasks
    tasks_by_ref = group_tasks_by_ref_id(build_tasks)

    # We don't need all the build tasks ids as
    # all them share the same ref_id
    failed_build_tasks = [
        tasks[0][0]
        for tasks in tasks_by_ref.values()
        if not any([task[1] for task in tasks])
    ]

    pkgs_blacklist = (await db.execute(
        select(models.BuildTaskArtifact.href).where(
            models.BuildTaskArtifact.type == "rpm",
            models.BuildTaskArtifact.name.like("%src.rpm"),
            models.BuildTaskArtifact.build_task_id.in_(failed_build_tasks),
        )
    )).scalars().all()

    return pkgs_blacklist


async def _perform_product_modification(
    build_id: int,
    product_id: int,
    modification: str,
):

    pulp_client = PulpClient(settings.pulp_host, settings.pulp_user,
                             settings.pulp_password)

    async with Session() as db, db.begin(): 
        db_product = (await db.execute(
            select(models.Product).where(
                models.Product.id == product_id
            ).options(
                selectinload(models.Product.builds),
                selectinload(models.Product.owner),
                selectinload(models.Product.platforms),
                selectinload(models.Product.repositories).selectinload(
                    models.Repository.platform
                )
            )
        )).scalars().first()

        db_build = await db.execute(
            select(models.Build).where(
                models.Build.id.__eq__(build_id),
            ).options(
                selectinload(models.Build.repos).selectinload(
                    models.Repository.platform
                ),
                selectinload(models.Build.tasks).selectinload(
                    models.BuildTask.rpm_module
                ),
                selectinload(models.Build.tasks).selectinload(
                    models.BuildTask.platform
                ),
            ),
        )
        db_build = db_build.scalars().first()

        pkgs_blacklist = []
        if modification == "add":
            pkgs_blacklist = await get_packages_to_blacklist(db, db_build.tasks)


    await set_platform_for_products_repos(db=db, product=db_product)
    await set_platform_for_build_repos(db=db, build=db_build)

    modify = await prepare_repo_modify_dict(
        db_build,
        db_product,
        pulp_client,
        modification,
        pkgs_blacklist
    )
    tasks = []
    publish_tasks = []
    for key, value in modify.items():
        if modification == "add":
            tasks.append(pulp_client.modify_repository(add=value, repo_to=key))
        else:
            tasks.append(pulp_client.modify_repository(
                remove=value, repo_to=key))
        # We've changed products repositories to not invoke
        # automatic publications, so now we need
        # to manually publish them after modification
        publish_tasks.append(pulp_client.create_rpm_publication(key))
    await asyncio.gather(*tasks)
    await asyncio.gather(*publish_tasks)

    if modification == "add":
        db_product.builds.append(db_build)
    else:
        db_product.builds.remove(db_build)
    db.add_all([
        db_product,
        db_build,
    ])
    try:
        await db.commit()
    except Exception:
        await db.rollback()


@dramatiq.actor(
    max_retries=0,
    priority=0,
    queue_name="product_modify",
    time_limit=DRAMATIQ_TASK_TIMEOUT
)
def perform_product_modification(
    build_id: int,
    product_id: int,
    modification: str,
):
    event_loop.run_until_complete(_perform_product_modification(
        build_id, product_id, modification
    ))
