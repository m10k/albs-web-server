import copy
import json
import logging
import typing
import urllib.parse

import aiohttp

from alws.constants import LOWEST_PRIORITY, REQUEST_TIMEOUT
from alws.models import Platform
from alws.utils.parsing import get_clean_distr_name


class BeholderClient:
    def __init__(
        self,
        host: str,
        token: str = "",
    ):
        self._host = host
        self._headers = {}
        if token:
            self._headers.update(
                {
                    "Authorization": f"Bearer {token}",
                }
            )
        self.__timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    @staticmethod
    def create_endpoints(
        platforms_list: typing.List[Platform],
        module_name: str = "",
        module_stream: str = "",
        module_arch_list: typing.Optional[typing.List[str]] = None,
    ) -> typing.Generator[str, None, None]:
        endpoints = (
            f"/api/v1/distros/{get_clean_distr_name(platform.name)}/"
            f"{platform.distr_version}/projects/"
            for platform in platforms_list
        )
        if module_name and module_stream and module_arch_list:
            endpoints = (
                f"/api/v1/distros/{get_clean_distr_name(platform.name)}/"
                f"{platform.distr_version}/module/{module_name}/"
                f"{module_stream}/{module_arch}/"
                for platform in platforms_list
                for module_arch in module_arch_list
            )
        return endpoints

    async def iter_endpoints(
        self,
        endpoints: typing.Iterable[str],
        data: typing.Optional[typing.Union[dict, list]] = None,
    ) -> typing.AsyncIterable[dict]:
        for endpoint in endpoints:
            try:
                coro = self.get(endpoint)
                if data:
                    coro = self.post(endpoint, data)
                yield await coro
            except Exception:
                logging.error(
                    "Cannot retrieve beholder info, "
                    "trying next reference platform"
                )

    async def retrieve_responses(
        self,
        platform: Platform,
        module_name: str = "",
        module_stream: str = "",
        module_arch_list: typing.Optional[typing.List[str]] = None,
        data: typing.Optional[typing.Union[dict, list]] = None,
    ) -> typing.List[dict]:
        platforms_list = platform.reference_platforms + [platform]
        endpoints = self.create_endpoints(
            platforms_list,
            module_name,
            module_stream,
            module_arch_list,
        )
        responses = []
        async for response in self.iter_endpoints(endpoints, data):
            response_distr_name = response["distribution"]["name"]
            response_distr_ver = response["distribution"]["version"]
            response["priority"] = next(
                db_platform.priority
                for db_platform in platforms_list
                if db_platform.name.startswith(response_distr_name)
                and db_platform.distr_version == response_distr_ver
            )
            # we have priority only in ref platforms
            response["priority"] = response.get("priority") or LOWEST_PRIORITY
            responses.append(response)
        return sorted(responses, key=lambda x: x["priority"], reverse=True)

    def _get_url(self, endpoint: str) -> str:
        return urllib.parse.urljoin(self._host, endpoint)

    async def get_module_artifacts(
        self,
        platform_name: str,
        platform_version: str,
        module_name: str,
        module_stream: str,
        arch: str,
    ):
        result = {}
        params = {"match": "closest"}
        for m_name in (module_name, f"{module_name}-devel"):
            endpoint = (
                f"/api/v1/distros/{platform_name}/"
                f"{platform_version}/module/{m_name}/"
                f"{module_stream}/{arch}/"
            )
            try:
                response = await self.get(endpoint, params=params)
                artifacts = {}
                for component in response["artifacts"]:
                    if not component.get("packages") or not component.get(
                        "sourcerpm"
                    ):
                        continue
                    packages = copy.copy(component["packages"])
                    srpm = copy.copy(component["sourcerpm"])

                    epoch = next(i["epoch"] for i in packages)
                    srpm["epoch"] = epoch
                    srpm["arch"] = "src"
                    packages.append(srpm)
                    artifacts[srpm["name"]] = packages

                result[m_name] = artifacts
            except Exception:
                pass
        return result

    async def get(
        self,
        endpoint: str,
        headers: typing.Optional[dict] = None,
        params: typing.Optional[dict] = None,
    ):
        req_headers = self._headers.copy()
        if headers:
            req_headers.update(**headers)
        full_url = self._get_url(endpoint)
        async with aiohttp.ClientSession(
            headers=req_headers,
            raise_for_status=True,
        ) as session:
            async with session.get(
                full_url,
                params=params,
                timeout=self.__timeout,
            ) as response:
                data = await response.read()
                json_data = json.loads(data)
                return json_data

    async def post(
        self,
        endpoint: str,
        data: typing.Union[dict, list],
    ):
        async with aiohttp.ClientSession(
            headers=self._headers,
            raise_for_status=True,
        ) as session:
            async with session.post(
                self._get_url(endpoint),
                json=data,
                timeout=self.__timeout,
            ) as response:
                content = await response.read()
                json_data = json.loads(content)
                return json_data
