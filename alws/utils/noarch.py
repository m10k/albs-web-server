import asyncio
import copy
import logging
import typing

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from alws import models
from alws.constants import BuildTaskStatus
from alws.utils.pulp_client import PulpClient


__all__ = [
    'get_noarch_packages',
    'save_noarch_packages',
]


async def get_noarch_packages(
    db: AsyncSession,
    build_task_ids: typing.List[int]
) -> typing.Tuple[dict, dict]:
    query = select(models.BuildTaskArtifact).where(sqlalchemy.and_(
        models.BuildTaskArtifact.build_task_id.in_(build_task_ids),
        models.BuildTaskArtifact.type == 'rpm',
        models.BuildTaskArtifact.name.like('%.noarch.%'),
    ))
    db_artifacts = await db.execute(query)
    db_artifacts = db_artifacts.scalars().all()
    noarch_packages = {}
    debug_noarch_packages = {}
    for artifact in db_artifacts:
        if '-debuginfo-' in artifact.name or '-debugsource-' in artifact.name:
            debug_noarch_packages[artifact.name] = (artifact.href,
                                                    artifact.cas_hash)
            continue
        noarch_packages[artifact.name] = (artifact.href, artifact.cas_hash)

    return noarch_packages, debug_noarch_packages


async def save_noarch_packages(
    db: AsyncSession,
    pulp_client: PulpClient,
    build_task: models.BuildTask,
):
    new_binary_rpms = []
    query = select(models.BuildTask).where(sqlalchemy.and_(
        models.BuildTask.build_id == build_task.build_id,
        models.BuildTask.index == build_task.index,
    )).options(
        selectinload(models.BuildTask.artifacts),
        selectinload(models.BuildTask.build).selectinload(models.Build.repos),
    )
    build_tasks = await db.execute(query)
    build_tasks = build_tasks.scalars().all()
    if not all(
            BuildTaskStatus.is_finished(task.status)
            for task in build_tasks):
        return new_binary_rpms

    logging.info("Start processing noarch packages")
    build_task_ids = [task.id for task in build_tasks]
    noarch_packages, debug_noarch_packages = await get_noarch_packages(
        db, build_task_ids)
    if not any((noarch_packages, debug_noarch_packages)):
        logging.info("Noarch packages doesn't found")
        return new_binary_rpms

    repos_to_update = {}
    new_noarch_artifacts = []
    hrefs_to_add = [href for href, _ in noarch_packages.values()]
    debug_hrefs_to_add = [href for href, _ in debug_noarch_packages.values()]

    for task in build_tasks:
        if task.status in (BuildTaskStatus.FAILED,
                           BuildTaskStatus.EXCLUDED):
            continue
        noarch = copy.deepcopy(noarch_packages)
        debug_noarch = copy.deepcopy(debug_noarch_packages)
        hrefs_to_delete = []
        debug_hrefs_to_delete = []

        # replace hrefs for existing artifacts in database
        # and create new artifacts if they doesn't exist
        for artifact in task.artifacts:
            if artifact.name in noarch:
                hrefs_to_delete.append(artifact.href)
                href, cas_hash = noarch.pop(artifact.name)
                artifact.href = href
                artifact.cas_hash = cas_hash
            if artifact.name in debug_noarch:
                debug_hrefs_to_delete.append(artifact.href)
                href, cas_hash = debug_noarch.pop(artifact.name)
                artifact.href = href
                artifact.cas_hash = cas_hash

        artifacts_to_create = {**noarch, **debug_noarch}
        for name, values in artifacts_to_create.items():
            href, cas_hash = values
            artifact = models.BuildTaskArtifact(
                build_task_id=task.id,
                name=name,
                type='rpm',
                href=href,
                cas_hash=cas_hash,
            )
            new_noarch_artifacts.append(artifact)
            if task.id != build_task.id:
                binary_rpm = models.BinaryRpm()
                binary_rpm.artifact = artifact
                binary_rpm.build = build_task.build
                new_binary_rpms.append(binary_rpm)

        for repo in build_task.build.repos:
            if (repo.arch == 'src' or repo.type != 'rpm'
                    or repo.arch != task.arch):
                continue
            repo_href = repo.pulp_href
            add_content = hrefs_to_add
            remove_content = hrefs_to_delete
            if repo.debug:
                add_content = debug_hrefs_to_add
                remove_content = debug_hrefs_to_delete
            repos_to_update[repo_href] = {
                'add': add_content,
                'remove': remove_content,
            }

    db.add_all(new_noarch_artifacts)
    await db.flush()

    await asyncio.gather(*(
        pulp_client.modify_repository(
            repo_href, add=content_dict['add'],
            remove=content_dict['remove'])
        for repo_href, content_dict in repos_to_update.items()
    ))

    logging.info("Noarch packages processing is finished")
    return new_binary_rpms
