import asyncio
import datetime
import logging
import re
import typing
import urllib.parse

import aiohttp.client_exceptions
from pydantic import AnyHttpUrl, BaseModel, conlist, validator

from alws import models
from alws.config import settings
from alws.constants import BuildTaskRefType
from alws.errors import EmptyBuildError
from alws.schemas.perf_stats_schema import PerformanceStats
from alws.utils.beholder_client import BeholderClient
from alws.utils.gitea import GiteaClient, download_modules_yaml
from alws.utils.modularity import (
    ModuleWrapper,
    RpmArtifact,
    get_modified_refs_list,
)
from alws.utils.parsing import clean_release, get_clean_distr_name

__all__ = ['BuildTaskRef', 'BuildCreate', 'Build', 'BuildsResponse']


class BuildTaskRef(BaseModel):
    url: AnyHttpUrl
    git_ref: typing.Optional[str]
    ref_type: typing.Optional[int]
    git_commit_hash: typing.Optional[str]
    mock_options: typing.Optional[typing.Dict[str, typing.Any]] = None
    is_module: typing.Optional[bool] = False
    enabled: bool = True
    added_artifacts: typing.Optional[list] = []
    module_platform_version: typing.Optional[str] = None
    module_version: typing.Optional[str] = None

    @property
    def git_repo_name(self):
        parsed_url = urllib.parse.urlparse(self.url)
        git_name = parsed_url.path.split('/')[-1]
        return git_name.replace('.git', '')

    def module_stream_from_ref(self):
        if 'stream-' in self.git_ref:
            return self.git_ref.split('stream-')[-1]
        return self.git_ref

    @validator('ref_type', pre=True)
    def ref_type_validator(cls, v):
        if isinstance(v, str):
            v = BuildTaskRefType.from_text(v)
        return v

    def ref_type_to_str(self):
        return BuildTaskRefType.to_text(self.ref_type)

    def get_dev_module(self) -> 'BuildTaskRef':
        model_copy = self.copy(deep=True)
        model_copy.url = self.url.replace(
            self.git_repo_name,
            self.git_repo_name + '-devel',
        )
        return model_copy

    class Config:
        orm_mode = True


class BuildTaskModuleRef(BaseModel):
    module_name: str
    module_stream: str
    module_platform_version: str
    module_version: typing.Optional[str] = None
    modules_yaml: str
    enabled_modules: dict
    refs: typing.List[BuildTaskRef]

    @validator('refs', pre=True)
    def refs_validator(cls, refs):
        if not refs or all((not ref['enabled'] for ref in refs)):
            raise EmptyBuildError(
                'refs are empty or doesn`t contain any enabled ref'
            )
        return refs


class BuildCreatePlatforms(BaseModel):
    name: str
    arch_list: typing.List[
        typing.Literal[
            'x86_64',
            'i686',
            'aarch64',
            'ppc64le',
            's390x',
        ]
    ]
    parallel_mode_enabled: bool


class BuildCreate(BaseModel):
    platforms: conlist(BuildCreatePlatforms, min_items=1)
    tasks: conlist(typing.Union[BuildTaskRef, BuildTaskModuleRef], min_items=1)
    linked_builds: typing.List[int] = []
    mock_options: typing.Optional[typing.Dict[str, typing.Any]]
    platform_flavors: typing.Optional[typing.List[int]] = None
    is_secure_boot: bool = False
    product_id: int


class BuildPlatform(BaseModel):
    id: int
    type: str
    name: str
    arch_list: typing.List[str]

    class Config:
        orm_mode = True


class BuildTaskArtifact(BaseModel):
    id: int
    name: str
    type: str
    href: str
    cas_hash: typing.Optional[str]

    class Config:
        orm_mode = True


class BuildTaskTestTask(BaseModel):
    id: int
    status: int
    revision: int
    performance_stats: typing.Optional[typing.List[PerformanceStats]] = None

    class Config:
        orm_mode = True


class BuildSignTask(BaseModel):
    id: int
    started_at: typing.Optional[datetime.datetime]
    finished_at: typing.Optional[datetime.datetime]
    status: int
    stats: typing.Optional[dict]

    class Config:
        orm_mode = True


class RpmModule(BaseModel):
    id: int
    name: str
    version: str
    stream: str
    context: str
    arch: str
    sha256: str

    class Config:
        orm_mode = True


class BuildTask(BaseModel):
    id: int
    ts: typing.Optional[datetime.datetime]
    started_at: typing.Optional[datetime.datetime]
    finished_at: typing.Optional[datetime.datetime]
    status: int
    index: int
    arch: str
    platform: BuildPlatform
    ref: BuildTaskRef
    rpm_module: typing.Optional[RpmModule]
    artifacts: typing.List[BuildTaskArtifact]
    is_cas_authenticated: typing.Optional[bool]
    alma_commit_cas_hash: typing.Optional[str]
    mock_options: typing.Optional[typing.Dict[str, typing.Any]] = None
    is_secure_boot: typing.Optional[bool]
    test_tasks: typing.List[BuildTaskTestTask]
    error: typing.Optional[str]
    performance_stats: typing.Optional[typing.List[PerformanceStats]] = None

    class Config:
        orm_mode = True


class BuildOwner(BaseModel):
    id: int
    username: str
    email: str

    class Config:
        orm_mode = True


class BuildCreateResponse(BaseModel):
    id: int
    created_at: datetime.datetime
    mock_options: typing.Optional[typing.Dict[str, typing.Any]]

    class Config:
        orm_mode = True


class PlatformFlavour(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True


class Product(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True


class Build(BaseModel):
    id: int
    created_at: datetime.datetime
    finished_at: typing.Optional[datetime.datetime]
    tasks: typing.List[BuildTask]
    owner: BuildOwner
    sign_tasks: typing.List[BuildSignTask]
    linked_builds: typing.Optional[typing.List[int]] = []
    mock_options: typing.Optional[typing.Dict[str, typing.Any]]
    platform_flavors: typing.List[PlatformFlavour]
    release_id: typing.Optional[int]
    released: bool
    products: typing.Optional[typing.List[Product]] = []

    @validator('linked_builds', pre=True)
    def linked_builds_validator(cls, v):
        return [item if isinstance(item, int) else item.id for item in v]

    class Config:
        orm_mode = True


class BuildsResponse(BaseModel):
    builds: typing.List[Build]
    total_builds: typing.Optional[int]
    current_page: typing.Optional[int]


class ModulePreviewRequest(BaseModel):
    ref: BuildTaskRef
    platform_name: str
    platform_arches: typing.List[str] = []
    flavors: typing.Optional[typing.List[int]] = None


class ModuleRef(BaseModel):
    url: str
    git_ref: str
    exist: bool
    enabled: bool = True
    added_artifacts: typing.Optional[list] = []
    mock_options: dict
    ref_type: int


class ModulePreview(BaseModel):
    refs: typing.List[ModuleRef]
    modules_yaml: str
    module_name: str
    module_stream: str
    enabled_modules: dict
    git_ref: typing.Optional[str]


async def get_module_data_from_beholder(
    beholder_client: BeholderClient,
    endpoint: str,
    arch: str,
    devel: bool = False,
) -> dict:
    result = {}
    if not settings.package_beholder_enabled:
        return result
    try:
        beholder_response = await beholder_client.get(endpoint)
    except Exception:
        logging.error('Cannot get module info')
        return result
    result['devel'] = devel
    result['arch'] = arch
    result['artifacts'] = beholder_response.get('artifacts', [])
    logging.info('Beholder result artifacts: %s', str(result['artifacts']))
    return result


def compare_module_data(
    component_name: str,
    beholder_data: typing.List[dict],
    tag_name: str,
) -> typing.List[dict]:
    pkgs_to_add = []
    for beholder_dict in beholder_data:
        beholder_artifact = None
        for artifact_dict in beholder_dict.get('artifacts', []):
            artifacr_srpm = artifact_dict.get('sourcerpm')
            if artifacr_srpm is None:
                continue
            if artifacr_srpm.get('name', '') == component_name:
                beholder_artifact = artifact_dict
                break
        if beholder_artifact is None:
            continue
        srpm = beholder_artifact['sourcerpm']
        beholder_tag_name = (
            f"{srpm['name']}-{srpm['version']}-" f"{srpm['release']}"
        )
        beholder_tag_name = clean_release(beholder_tag_name)
        if beholder_tag_name != tag_name:
            continue
        for package in beholder_artifact['packages']:
            package['devel'] = beholder_dict.get('devel', False)
            pkgs_to_add.append(package)
    return pkgs_to_add


async def _get_module_ref(
    component_name: str,
    modified_list: list,
    platform_prefix_list: list,
    module: ModuleWrapper,
    gitea_client: GiteaClient,
    devel_module: typing.Optional[ModuleWrapper],
    platform_packages_git: str,
    beholder_data: typing.List[dict],
):
    ref_prefix = platform_prefix_list['non_modified']
    if component_name in modified_list:
        ref_prefix = platform_prefix_list['modified']
    # gitea doesn't support + in repo names
    gitea_component_name = re.sub(r"\+", "-", component_name)
    git_ref = f'{ref_prefix}-stream-{module.stream}'
    exist = True
    commit_id = ''
    enabled = True
    pkgs_to_add = []
    added_packages = []
    clean_tag_name = ''
    try:
        response = await gitea_client.get_branch(
            f'rpms/{gitea_component_name}', git_ref
        )
        commit_id = response['commit']['id']
    except aiohttp.client_exceptions.ClientResponseError as e:
        if e.status == 404:
            exist = False
    if commit_id:
        tags = await gitea_client.list_tags(f'rpms/{gitea_component_name}')
        raw_tag_name = next(
            (tag['name'] for tag in tags if tag['id'] == commit_id),
            None,
        )
        if raw_tag_name is not None:
            # we need only last part from tag to comparison
            # imports/c8-stream-rhel8/golang-1.16.7-1.module+el8.5.0+12+1aae3f
            tag_name = raw_tag_name.split('/')[-1]
            clean_tag_name = clean_release(tag_name)
            pkgs_to_add = compare_module_data(
                component_name,
                beholder_data,
                clean_tag_name,
            )
            enabled = not pkgs_to_add
    for pkg_dict in pkgs_to_add:
        if pkg_dict['devel']:
            continue
        module.add_rpm_artifact(pkg_dict)
        added_packages.append(
            RpmArtifact.from_pulp_model(pkg_dict).as_artifact()
        )
    module.set_component_ref(component_name, commit_id)
    if devel_module:
        devel_module.set_component_ref(component_name, commit_id)
        for pkg_dict in pkgs_to_add:
            if not pkg_dict['devel']:
                continue
            devel_module.add_rpm_artifact(pkg_dict, devel=True)
            added_packages.append(
                RpmArtifact.from_pulp_model(pkg_dict).as_artifact()
            )
    return ModuleRef(
        url=f'{platform_packages_git}{gitea_component_name}.git',
        git_ref=git_ref,
        exist=exist,
        added_artifacts=added_packages,
        enabled=enabled,
        mock_options={
            'definitions': dict(module.iter_mock_definitions()),
        },
        ref_type=BuildTaskRefType.GIT_BRANCH,
    )


async def get_module_refs(
    task: BuildTaskRef,
    platform: models.Platform,
    flavors: typing.List[models.PlatformFlavour],
    platform_arches: typing.List[str] = None,
) -> typing.Tuple[
    typing.List[ModuleRef],
    typing.List[str],
    typing.Dict[str, typing.Any],
]:
    gitea_client = GiteaClient(
        settings.gitea_host,
        logging.getLogger(__name__),
    )

    beholder_client = BeholderClient(
        host=settings.beholder_host,
        token=settings.beholder_token,
    )
    clean_dist_name = get_clean_distr_name(platform.name)
    distr_ver = platform.distr_version
    modified_list = await get_modified_refs_list(
        platform.modularity['modified_packages_url']
    )
    template = await download_modules_yaml(
        task.url, task.git_ref, BuildTaskRefType.to_text(task.ref_type)
    )
    devel_module = None
    module = ModuleWrapper.from_template(
        template,
        name=task.git_repo_name,
        stream=task.module_stream_from_ref(),
    )
    if not module.is_devel:
        devel_module = ModuleWrapper.from_template(
            template,
            name=f'{task.git_repo_name}-devel',
            stream=task.module_stream_from_ref(),
        )

    has_beta_flafor = False
    for flavor in flavors:
        if bool(re.search(r'(-beta)$', flavor.name, re.IGNORECASE)):
            has_beta_flafor = True
            break

    checking_tasks = []
    if platform_arches is None:
        platform_arches = []
    for arch in platform_arches:
        request_arch = arch
        if arch == 'i686':
            request_arch = 'x86_64'
        for _module in (module, devel_module):
            if _module is None:
                continue
            # if module is devel and devel_module is None
            # we shouldn't mark module as devel, because it will broke logic
            # for partially updating modules
            module_is_devel = _module.is_devel and devel_module is not None
            endpoint = (
                f'/api/v1/distros/{clean_dist_name}/{distr_ver}'
                f'/module/{_module.name}/{_module.stream}/{request_arch}/'
            )
            checking_tasks.append(
                get_module_data_from_beholder(
                    beholder_client,
                    endpoint,
                    arch,
                    devel=module_is_devel,
                )
            )

            if has_beta_flafor:
                endpoint = (
                    f'/api/v1/distros/{clean_dist_name}-beta/{distr_ver}'
                    f'/module/{_module.name}/{_module.stream}/{request_arch}/'
                )
                checking_tasks.append(
                    get_module_data_from_beholder(
                        beholder_client,
                        endpoint,
                        arch,
                        devel=module_is_devel,
                    )
                )
    beholder_results = await asyncio.gather(*checking_tasks)

    platform_prefix_list = platform.modularity['git_tag_prefix']
    for flavor in flavors:
        if flavor.modularity and flavor.modularity.get('git_tag_prefix'):
            platform_prefix_list = flavor.modularity['git_tag_prefix']
    platform_packages_git = platform.modularity['packages_git']
    component_tasks = []
    for component_name, _ in module.iter_components():
        component_tasks.append(
            _get_module_ref(
                component_name=component_name,
                modified_list=modified_list,
                platform_prefix_list=platform_prefix_list,
                module=module,
                gitea_client=gitea_client,
                devel_module=devel_module,
                platform_packages_git=platform_packages_git,
                beholder_data=beholder_results,
            )
        )
    result = list(await asyncio.gather(*component_tasks))
    enabled_modules = module.get_all_build_deps()
    modules = [module.render()]
    if devel_module:
        modules.append(devel_module.render())
    return result, modules, enabled_modules
