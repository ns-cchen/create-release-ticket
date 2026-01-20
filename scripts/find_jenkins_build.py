import json

import httpx

from create_release_ticket.config import get_app_config, get_settings


def main() -> None:
    settings = get_settings()
    app = get_app_config()
    job = app.jenkins.job_name
    base = settings.jenkins_url.rstrip("/")

    want_release = "queryservice-release-2026.1.4.0.18836"
    want_ticket = "ENG-864203"

    api = f"{base}/job/{job}/api/json"
    query = {
        "tree": "builds[number,url,result,building,actions[parameters[name,value]]]",
    }

    with httpx.Client(
        auth=(settings.jenkins_user, settings.jenkins_api_token),
        timeout=30,
    ) as client:
        resp = client.get(api, params=query)
        resp.raise_for_status()
        payload = resp.json()

    matches: list[dict[str, object]] = []
    for build in (payload.get("builds") or [])[:200]:
        params_list = []
        for action in (build.get("actions") or []):
            if isinstance(action, dict) and action.get("parameters"):
                params_list = action.get("parameters") or []
                break

        params: dict[str, object] = {}
        for item in params_list:
            if isinstance(item, dict):
                params[str(item.get("name"))] = item.get("value")

        if params.get("RELEASE") == want_release and params.get("TICKET") == want_ticket:
            matches.append(
                {
                    "number": build.get("number"),
                    "url": build.get("url"),
                    "result": build.get("result"),
                    "building": build.get("building"),
                    "STORK_COMPONENT_NAME": params.get("STORK_COMPONENT_NAME"),
                }
            )

    print("Found", len(matches), "matching build(s)")
    print(json.dumps(matches[:20], indent=2))


if __name__ == "__main__":
    main()
