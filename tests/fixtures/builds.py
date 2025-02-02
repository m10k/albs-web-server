import typing

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from alws.crud.build import create_build, get_builds
from alws.models import Build
from alws.schemas.build_schema import BuildCreate
from tests.constants import ADMIN_USER_ID
from tests.test_utils.pulp_utils import get_rpm_pkg_info


@pytest.fixture(
    params=[
        [],
        [
            {
                "url": "https://git.almalinux.org/rpms/go-toolset.git",
                "git_ref": "c8-stream-rhel8",
                "exist": True,
                "enabled": False,
                "added_artifacts": [],
                "mock_options": {
                    "definitions": {},
                    "module_enable": [
                        "go-toolset:rhel8",
                        "go-toolset-devel:rhel8",
                    ],
                },
                "ref_type": 1,
            },
            {
                "url": "https://git.almalinux.org/rpms/golang.git",
                "git_ref": "c8-stream-rhel8",
                "exist": True,
                "enabled": False,
                "added_artifacts": [],
                "mock_options": {
                    "definitions": {},
                    "module_enable": [
                        "go-toolset:rhel8",
                        "go-toolset-devel:rhel8",
                    ],
                },
                "ref_type": 1,
            },
            {
                "url": "https://git.almalinux.org/rpms/delve.git",
                "git_ref": "c8-stream-rhel8",
                "exist": True,
                "enabled": False,
                "added_artifacts": [],
                "mock_options": {
                    "definitions": {},
                    "module_enable": [
                        "go-toolset:rhel8",
                        "go-toolset-devel:rhel8",
                    ],
                },
                "ref_type": 1,
            },
        ],
    ],
    ids=[
        "empty_refs",
        "only_disabled_refs",
    ],
)
def nonvalid_modular_build_payload(request) -> typing.Dict[str, typing.Any]:
    return {
        "platforms": [
            {
                "name": "AlmaLinux-8",
                "arch_list": ["i686", "x86_64"],
                "parallel_mode_enabled": True,
            }
        ],
        "tasks": [
            {
                "refs": request.param,
                "modules_yaml": '---\ndocument: modulemd\nversion: 2\ndata:\n  name: go-toolset\n  stream: "rhel8"\n  arch: x86_64\n  summary: Go\n  description: >-\n    Go Tools and libraries\n  license:\n    module:\n    - MIT\n  dependencies:\n  - buildrequires:\n      go-toolset: [rhel8]\n      platform: [el8]\n    requires:\n      platform: [el8]\n  profiles:\n    common:\n      rpms:\n      - go-toolset\n  api:\n    rpms:\n    - golang\n  buildopts:\n    rpms:\n      whitelist:\n      - delve\n      - go-toolset\n      - go-toolset-1.10\n      - go-toolset-1.10-golang\n      - go-toolset-golang\n      - golang\n  components:\n    rpms:\n      delve:\n        rationale: A debugger for the Go programming language\n        ref: 18f55f0e6d4d9579ac949e3a96c1c2f6e877cba8\n        buildorder: 2\n      go-toolset:\n        rationale: Meta package for go-toolset providing scl enable scripts.\n        ref: feda7855f214faf3cbb4324c74a47e4a00d117a8\n      golang:\n        rationale: Package providing the Go compiler toolchain.\n        ref: 61d02fbf0e5553e82c220cfb2f403338f43496b6\n        buildorder: 1\n...\n\n---\ndocument: modulemd\nversion: 2\ndata:\n  name: go-toolset-devel\n  stream: "rhel8"\n  summary: Go\n  description: >-\n    Go Tools and libraries\n  license:\n    module:\n    - MIT\n  dependencies:\n  - buildrequires:\n      go-toolset: [rhel8]\n      platform: [el8]\n    requires:\n      platform: [el8]\n  profiles:\n    common:\n      rpms:\n      - go-toolset\n  api:\n    rpms:\n    - golang\n  buildopts:\n    rpms:\n      whitelist:\n      - delve\n      - go-toolset\n      - go-toolset-1.10\n      - go-toolset-1.10-golang\n      - go-toolset-golang\n      - golang\n  components:\n    rpms:\n      delve:\n        rationale: A debugger for the Go programming language\n        ref: 18f55f0e6d4d9579ac949e3a96c1c2f6e877cba8\n        buildorder: 2\n      go-toolset:\n        rationale: Meta package for go-toolset providing scl enable scripts.\n        ref: feda7855f214faf3cbb4324c74a47e4a00d117a8\n      golang:\n        rationale: Package providing the Go compiler toolchain.\n        ref: 61d02fbf0e5553e82c220cfb2f403338f43496b6\n        buildorder: 1\n...\n',
                "module_name": "go-toolset",
                "module_stream": "rhel8",
                "enabled_modules": {"buildtime": [], "runtime": []},
                "git_ref": "c8-stream-rhel8",
                "module_platform_version": "8.6",
                "enabled_modules_table": [
                    {
                        "name": "go-toolset",
                        "stream": "rhel8",
                        "main": True,
                        "enable": True,
                    },
                    {
                        "name": "go-toolset-devel",
                        "stream": "rhel8",
                        "main": True,
                        "enable": True,
                    },
                ],
                "selectedModules": {},
            }
        ],
        "linked_builds": [],
        "is_secure_boot": False,
        "mock_options": {},
        "platform_flavors": [],
        "product_id": 1,
    }


@pytest.fixture
def modular_build_payload() -> typing.Dict[str, typing.Any]:
    return {
        "platforms": [
            {
                "name": "AlmaLinux-8",
                "arch_list": ["i686", "x86_64"],
                "parallel_mode_enabled": True,
            }
        ],
        "tasks": [
            {
                "refs": [
                    {
                        "url": "https://git.almalinux.org/rpms/go-toolset.git",
                        "git_ref": "c8-stream-rhel8",
                        "exist": True,
                        "enabled": True,
                        "added_artifacts": [],
                        "mock_options": {
                            "definitions": {},
                            "module_enable": [
                                "go-toolset:rhel8",
                                "go-toolset-devel:rhel8",
                            ],
                        },
                        "ref_type": 1,
                    },
                    {
                        "url": "https://git.almalinux.org/rpms/golang.git",
                        "git_ref": "c8-stream-rhel8",
                        "exist": True,
                        "enabled": True,
                        "added_artifacts": [],
                        "mock_options": {
                            "definitions": {},
                            "module_enable": [
                                "go-toolset:rhel8",
                                "go-toolset-devel:rhel8",
                            ],
                        },
                        "ref_type": 1,
                    },
                    {
                        "url": "https://git.almalinux.org/rpms/delve.git",
                        "git_ref": "c8-stream-rhel8",
                        "exist": True,
                        "enabled": True,
                        "added_artifacts": [],
                        "mock_options": {
                            "definitions": {},
                            "module_enable": [
                                "go-toolset:rhel8",
                                "go-toolset-devel:rhel8",
                            ],
                        },
                        "ref_type": 1,
                    },
                ],
                "modules_yaml": '---\ndocument: modulemd\nversion: 2\ndata:\n  name: go-toolset\n  stream: "rhel8"\n  arch: x86_64\n  summary: Go\n  description: >-\n    Go Tools and libraries\n  license:\n    module:\n    - MIT\n  dependencies:\n  - buildrequires:\n      go-toolset: [rhel8]\n      platform: [el8]\n    requires:\n      platform: [el8]\n  profiles:\n    common:\n      rpms:\n      - go-toolset\n  api:\n    rpms:\n    - golang\n  buildopts:\n    rpms:\n      whitelist:\n      - delve\n      - go-toolset\n      - go-toolset-1.10\n      - go-toolset-1.10-golang\n      - go-toolset-golang\n      - golang\n  components:\n    rpms:\n      delve:\n        rationale: A debugger for the Go programming language\n        ref: 18f55f0e6d4d9579ac949e3a96c1c2f6e877cba8\n        buildorder: 2\n      go-toolset:\n        rationale: Meta package for go-toolset providing scl enable scripts.\n        ref: feda7855f214faf3cbb4324c74a47e4a00d117a8\n      golang:\n        rationale: Package providing the Go compiler toolchain.\n        ref: 61d02fbf0e5553e82c220cfb2f403338f43496b6\n        buildorder: 1\n...\n\n---\ndocument: modulemd\nversion: 2\ndata:\n  name: go-toolset-devel\n  stream: "rhel8"\n  summary: Go\n  description: >-\n    Go Tools and libraries\n  license:\n    module:\n    - MIT\n  dependencies:\n  - buildrequires:\n      go-toolset: [rhel8]\n      platform: [el8]\n    requires:\n      platform: [el8]\n  profiles:\n    common:\n      rpms:\n      - go-toolset\n  api:\n    rpms:\n    - golang\n  buildopts:\n    rpms:\n      whitelist:\n      - delve\n      - go-toolset\n      - go-toolset-1.10\n      - go-toolset-1.10-golang\n      - go-toolset-golang\n      - golang\n  components:\n    rpms:\n      delve:\n        rationale: A debugger for the Go programming language\n        ref: 18f55f0e6d4d9579ac949e3a96c1c2f6e877cba8\n        buildorder: 2\n      go-toolset:\n        rationale: Meta package for go-toolset providing scl enable scripts.\n        ref: feda7855f214faf3cbb4324c74a47e4a00d117a8\n      golang:\n        rationale: Package providing the Go compiler toolchain.\n        ref: 61d02fbf0e5553e82c220cfb2f403338f43496b6\n        buildorder: 1\n...\n',
                "module_name": "go-toolset",
                "module_stream": "rhel8",
                "enabled_modules": {"buildtime": [], "runtime": []},
                "git_ref": "c8-stream-rhel8",
                "module_platform_version": "8.6",
                "enabled_modules_table": [
                    {
                        "name": "go-toolset",
                        "stream": "rhel8",
                        "main": True,
                        "enable": True,
                    },
                    {
                        "name": "go-toolset-devel",
                        "stream": "rhel8",
                        "main": True,
                        "enable": True,
                    },
                ],
                "selectedModules": {},
            }
        ],
        "linked_builds": [],
        "is_secure_boot": False,
        "mock_options": {},
        "platform_flavors": [],
        "product_id": 1,
    }


@pytest.fixture
def build_payload() -> typing.Dict[str, typing.Any]:
    return {
        "platforms": [
            {
                "name": "AlmaLinux-8",
                "arch_list": ["i686", "x86_64"],
                "parallel_mode_enabled": True,
            }
        ],
        "tasks": [
            {
                "git_ref": "c8",
                "url": "https://git.almalinux.org/rpms/chan.git",
                "ref_type": 4,
                "mock_options": {},
            }
        ],
        "linked_builds": [],
        "is_secure_boot": False,
        "mock_options": {},
        "platform_flavors": [],
        "product_id": 1,
    }


@pytest.mark.anyio
@pytest.fixture
async def modular_build(
    session: AsyncSession,
    modular_build_payload: dict,
) -> typing.AsyncIterable[Build]:
    yield await create_build(
        session,
        BuildCreate(**modular_build_payload),
        user_id=ADMIN_USER_ID,
    )


@pytest.mark.anyio
@pytest.fixture
async def regular_build(
    session: AsyncSession,
    build_payload: dict,
) -> typing.AsyncIterable[Build]:
    yield await create_build(
        session,
        BuildCreate(**build_payload),
        user_id=ADMIN_USER_ID,
    )


@pytest.fixture
def get_rpm_packages_info(monkeypatch):
    def func(artifacts):
        return {
            artifact.href: get_rpm_pkg_info(artifact) for artifact in artifacts
        }

    monkeypatch.setattr("alws.crud.build_node.get_rpm_packages_info", func)


@pytest.mark.anyio
@pytest.fixture
async def build_for_release(
    session: AsyncSession,
    regular_build: Build,
) -> typing.AsyncIterable[Build]:
    yield await get_builds(session, build_id=regular_build.id)


@pytest.mark.anyio
@pytest.fixture
async def modular_build_for_release(
    session: AsyncSession,
    modular_build: Build,
) -> typing.AsyncIterable[Build]:
    yield await get_builds(session, build_id=modular_build.id)
