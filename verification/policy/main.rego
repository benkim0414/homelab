package main

import rego.v1

encode_violation(rule, resource) := json.marshal({"rule": rule, "resource": resource})

resource_id(resource) := concat("/", [group, resource.kind, object.get(resource.metadata, "namespace", ""), resource.metadata.name]) if {
    parts := split(resource.apiVersion, "/")
    group := trim_suffix(resource.apiVersion, concat("", ["/", parts[count(parts)-1]]))
    count(parts) > 1
}
resource_id(resource) := concat("/", ["", resource.kind, object.get(resource.metadata, "namespace", ""), resource.metadata.name]) if {
    not contains(resource.apiVersion, "/")
}

deny contains encode_violation("automated-sync", resource_id(app)) if {
    some app in input.applications
    object.get(object.get(app.spec, "syncPolicy", {}), "automated", null) != null
}

deny contains encode_violation("unsafe-sync", resource_id(app)) if {
    some app in input.applications
    some option in object.get(object.get(app.spec, "syncPolicy", {}), "syncOptions", [])
    option in {"Force=true", "Replace=true", "Prune=true"}
}

deny contains encode_violation("unsafe-sync", resource_id(resource)) if {
    some resource in input.resources
    options := object.get(object.get(resource.metadata, "annotations", {}), "argocd.argoproj.io/sync-options", "")
    some option in split(options, ",")
    trim_space(option) in {"Force=true", "Replace=true", "Prune=true"}
}

deny contains encode_violation("committed-secret", resource_id(resource)) if {
    some resource in input.committed
    resource.kind == "Secret"
    some field in {"data", "stringData"}
    count(object.get(resource, field, {})) > 0
}

expected_ignores := [
    {"kind": "Secret", "name": "kube-prometheus-stack-grafana", "jsonPointers": ["/data/admin-password", "/data/admin-user"]},
    {"group": "apps", "kind": "Deployment", "name": "kube-prometheus-stack-grafana", "jsonPointers": ["/spec/template/metadata/annotations/checksum~1secret"]}
]

deny contains encode_violation("monitoring-ignore", resource_id(app)) if {
    some app in input.applications
    app.metadata.name == "kube-prometheus-stack"
    object.get(app.spec, "ignoreDifferences", []) != expected_ignores
}

deny contains encode_violation("monitoring-ignore", resource_id(app)) if {
    some app in input.applications
    app.metadata.name == "kube-prometheus-stack"
    not "RespectIgnoreDifferences=true" in app.spec.syncPolicy.syncOptions
}

deny contains encode_violation("tailscale-release", resource_id(app)) if {
    some app in input.applications
    app.metadata.name == "tailscale"
    some source in app.spec.sources
    source.chart == "tailscale-operator"
    object.get(object.get(source, "helm", {}), "releaseName", "") != "tailscale-operator"
}
