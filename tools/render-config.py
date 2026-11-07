#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from string import Template


REQUIRED = [
    "LOCAL_PROXY_PORT",
    "MIHOMO_API_PORT",
    "NETWORK_SERVICE",
    "RELAY_SSH_TARGET",
    "RELAY_SING_BOX_CONFIG_PATH",
    "RELAY_SING_BOX_SERVICE",
    "AI_RELAY_HOST",
    "AI_RELAY_PORT",
    "HY2_PASSWORD",
    "HY2_SNI",
    "HY2_SKIP_CERT_VERIFY",
    "HY2_UP",
    "HY2_DOWN",
    "STABLE_EGRESS_HTTP_HOST",
    "STABLE_EGRESS_HTTP_PORT",
    "STABLE_EGRESS_HTTP_USERNAME",
    "STABLE_EGRESS_HTTP_PASSWORD",
    "AI_DOMAINS",
]


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"Invalid env line: {raw}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not re.fullmatch(r"[A-Z0-9_]+", key):
            raise SystemExit(f"Invalid env key: {key}")
        values[key] = value
    missing = [key for key in REQUIRED if not values.get(key)]
    if missing:
        raise SystemExit("Missing required values: " + ", ".join(missing))
    return values


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def indented_yaml_map(domains: list[str], value: str, indent: int = 4) -> str:
    prefix = " " * indent
    if not domains:
        return f"{prefix}# no entries\n"
    return "".join(f'{prefix}"+.{domain}": {value}\n' for domain in domains)


def domain_rules(domains: list[str], target: str, indent: int = 2) -> str:
    prefix = " " * indent
    if not domains:
        return f"{prefix}# no {target} domain rules\n"
    return "".join(f"{prefix}- DOMAIN-SUFFIX,{domain},{target}\n" for domain in domains)


def host_direct_rule(host: str, indent: int = 2) -> str:
    prefix = " " * indent
    if not host:
        return ""
    if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
        return f"{prefix}- IP-CIDR,{host}/32,DIRECT,no-resolve\n"
    return f"{prefix}- DOMAIN,{host},DIRECT\n"


def render_template(src: Path, dst: Path, values: dict[str, str]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = Template(src.read_text()).safe_substitute(values)
    dst.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render AgentRouteKit configs.")
    parser.add_argument("--env", default="agent-input.env", help="private env input file")
    parser.add_argument("--out", default="build", help="output directory")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    values = parse_env(Path(args.env))

    ai_domains = csv_list(values["AI_DOMAINS"])
    corporate_domains = csv_list(values.get("CORPORATE_DOMAINS", ""))
    direct_domains = csv_list(values.get("DIRECT_DOMAINS", ""))

    # Port hopping
    hy2_ports = values.get("HY2_PORTS", "").strip()
    hy2_ports_line = f"    ports: {hy2_ports}\n" if hy2_ports else ""

    # Reality fallback
    enable_reality = values.get("ENABLE_REALITY", "false").lower() in ("true", "1", "yes") or bool(values.get("REALITY_UUID"))
    reality_port = values.get("REALITY_PORT", "8443").strip()
    reality_uuid = values.get("REALITY_UUID", "").strip()
    reality_sni = values.get("REALITY_SNI", "gateway.icloud.com").strip()
    reality_priv_key = values.get("REALITY_PRIVATE_KEY", "").strip()
    reality_pub_key = values.get("REALITY_PUBLIC_KEY", "").strip()
    reality_short_id = values.get("REALITY_SHORT_ID", "a1b2c3d4e5f60718").strip()

    if enable_reality and reality_uuid:
        reality_inbound_json = f''',
    {{
      "type": "vless",
      "tag": "vless-reality-in",
      "listen": "::",
      "listen_port": {reality_port},
      "users": [
        {{
          "uuid": "{reality_uuid}",
          "flow": "xtls-rprx-vision"
        }}
      ],
      "tls": {{
        "enabled": true,
        "server_name": "{reality_sni}",
        "reality": {{
          "enabled": true,
          "handshake": {{
            "server": "{reality_sni}",
            "server_port": 443
          }},
          "private_key": "{reality_priv_key}",
          "short_id": [
            "{reality_short_id}"
          ]
        }}
      }}
    }}'''
        reality_proxies_yaml = f'''  - name: ai-relay-tcp
    type: vless
    server: {values["AI_RELAY_HOST"]}
    port: {reality_port}
    uuid: {reality_uuid}
    network: tcp
    tls: true
    udp: true
    flow: xtls-rprx-vision
    servername: {reality_sni}
    reality-opts:
      public-key: {reality_pub_key}
      short-id: {reality_short_id}
    client-fingerprint: chrome
'''
        proxy_groups_yaml = '''  - name: ai-relay-group
    type: fallback
    proxies:
      - ai-relay
      - ai-relay-tcp
    url: "http://www.gstatic.com/generate_204"
    interval: 60

  - name: MODE
    type: select
    proxies:
      - Global
      - AI Only
      - Bypass

  - name: Global
    type: select
    proxies: [ai-relay-group, ai-relay, ai-relay-tcp]

  - name: AI Only
    type: select
    proxies: [DIRECT]

  - name: Bypass
    type: select
    proxies: [DIRECT]

  - name: ai-route
    type: select
    proxies: [ai-relay-group, ai-relay, ai-relay-tcp, DIRECT]
'''
        fallback_dns_target = "ai-relay-group"
    else:
        reality_inbound_json = ""
        reality_proxies_yaml = ""
        proxy_groups_yaml = '''  - name: MODE
    type: select
    proxies:
      - Global
      - AI Only
      - Bypass

  - name: Global
    type: select
    proxies: [ai-relay]

  - name: AI Only
    type: select
    proxies: [DIRECT]

  - name: Bypass
    type: select
    proxies: [DIRECT]

  - name: ai-route
    type: select
    proxies: [ai-relay, DIRECT]
'''
        fallback_dns_target = "ai-relay"

    # Relay and egress direct bypass rules (prevents TUN routing loops)
    relay_direct_rules = host_direct_rule(values["AI_RELAY_HOST"]) + host_direct_rule(values["STABLE_EGRESS_HTTP_HOST"])

    # DNS policy decoupling: direct domains resolve locally without touching fallback DNS
    direct_dns_lines = []
    if direct_domains:
        direct_dns_lines.append('    "rule-set:cn": [223.5.5.5, 119.29.29.29]\n')
        for d in direct_domains:
            direct_dns_lines.append(f'    "+.{d}": [223.5.5.5, 119.29.29.29]\n')
    direct_dns_policy = "".join(direct_dns_lines)

    values = {
        **values,
        "AI_DOMAIN_JSON_ARRAY": json.dumps(ai_domains, indent=8),
        "AI_RULES": domain_rules(ai_domains, "ai-route"),
        "CORPORATE_DNS_POLICY": indented_yaml_map(corporate_domains, "system"),
        "DIRECT_DNS_POLICY": direct_dns_policy,
        "CORPORATE_RULES": domain_rules(corporate_domains, "DIRECT"),
        "DIRECT_DOMAIN_RULES": domain_rules(direct_domains, "DIRECT"),
        "HY2_PORTS_LINE": hy2_ports_line,
        "REALITY_INBOUND_JSON": reality_inbound_json,
        "REALITY_PROXIES_YAML": reality_proxies_yaml,
        "PROXY_GROUPS_YAML": proxy_groups_yaml,
        "FALLBACK_DNS_TARGET": fallback_dns_target,
        "RELAY_DIRECT_RULES": relay_direct_rules,
    }

    out = Path(args.out)
    render_template(root / "configs/mihomo/config.template.yaml", out / "mihomo/config.yaml", values)
    render_template(root / "configs/sing-box/relay.template.json", out / "sing-box/config.json", values)
    render_template(root / "configs/claude-code/settings.template.json", out / "claude-code/settings.json", values)

    metadata = {
        "local_proxy": f"127.0.0.1:{values['LOCAL_PROXY_PORT']}",
        "mihomo_api": f"127.0.0.1:{values['MIHOMO_API_PORT']}",
        "relay_ssh_target": values["RELAY_SSH_TARGET"],
        "relay_config_path": values["RELAY_SING_BOX_CONFIG_PATH"],
        "relay_service": values["RELAY_SING_BOX_SERVICE"],
        "ai_domains": ai_domains,
        "corporate_domains_count": len(corporate_domains),
        "direct_domains_count": len(direct_domains),
        "reality_enabled": bool(enable_reality and reality_uuid),
        "port_hopping": hy2_ports if hy2_ports else "disabled",
    }
    (out / "deployment-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Rendered configs to {out}")


if __name__ == "__main__":
    main()
