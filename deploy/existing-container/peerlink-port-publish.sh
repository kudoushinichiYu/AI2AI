#!/bin/sh
set -eu

container_name="jdme-bot"
host_ip="11.91.168.198"
host_port="18083"

container_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$container_name")"
bridge_name="$(ip route get "$container_ip" | awk '{for (field_number = 1; field_number <= NF; field_number++) if ($field_number == "dev") { print $(field_number + 1); exit }}')"

nat_rule="-d $host_ip/32 ! -i $bridge_name -p tcp -m tcp --dport $host_port -j DNAT --to-destination $container_ip:$host_port"
filter_rule="-d $container_ip/32 ! -i $bridge_name -o $bridge_name -p tcp -m tcp --dport $host_port -j ACCEPT"

add_rules() {
    iptables -t nat -C DOCKER $nat_rule 2>/dev/null || iptables -t nat -I DOCKER 1 $nat_rule
    iptables -C DOCKER $filter_rule 2>/dev/null || iptables -I DOCKER 1 $filter_rule
}

remove_rules() {
    iptables -t nat -D DOCKER $nat_rule 2>/dev/null || true
    iptables -D DOCKER $filter_rule 2>/dev/null || true
}

case "${1:-start}" in
    start) add_rules ;;
    stop) remove_rules ;;
    *) echo "Usage: $0 {start|stop}" >&2; exit 2 ;;
esac
