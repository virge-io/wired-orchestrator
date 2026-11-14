# Copyright 2019-2023 SURF.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    NETBOX_URL: str = "http://netbox:8080"
    NETBOX_TOKEN: str = ""
    IPv4_LOOPBACK_PREFIX: str = "10.0.127.0/24"
    IPv6_LOOPBACK_PREFIX: str = "fc00:0:0:127::/64"
    IPv4_CORE_LINK_PREFIX: str = "10.0.10.0/24"
    IPv6_CORE_LINK_PREFIX: str = "fc00:0:0:10::/64"

    # Campus / CNaaS-NMS integration
    CNAAS_ENABLED: bool = False  # False = mock mode: no calls to CNaaS, workflows still run end-to-end
    CNAAS_API_URL: str = "https://cnaas_api:1443/api/v1.0"
    CNAAS_TOKEN: str = ""
    CNAAS_TOKEN_FILE: str = "/opt/cnaas/jwt/token"  # written by the cnaas-jwt init container
    CNAAS_VERIFY_TLS: bool = False
    CNAAS_JOB_TIMEOUT: int = 900
    CNAAS_SETTINGS_REPO: str = "/opt/cnaas/git/settings.git"  # bare repo served by cnaas-git
    CAMPUS_SITE_SLUG: str = "campus"
    CAMPUS_MGMT_PREFIX: str = "10.100.0.0/24"
    CAMPUS_MGMT_VLAN: int = 10
    CAMPUS_LOOPBACK_PREFIX: str = "10.100.255.0/24"


settings = Settings()
