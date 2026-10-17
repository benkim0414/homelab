package main

import rego.v1

empty_input := {"applications": [], "committed": [], "resources": []}
app := {"apiVersion": "argoproj.io/v1alpha1", "kind": "Application", "metadata": {"name": "test", "namespace": "argocd"}, "spec": {}}

test_manual_sync_allowed if {
    result := deny with input as object.union(empty_input, {"applications": [app]})
    count(result) == 0
}

test_empty_automated_block_rejected if {
    automated := object.union(app, {"spec": {"syncPolicy": {"automated": {}}}})
    result := deny with input as object.union(empty_input, {"applications": [automated]})
    count(result) == 1
}

test_secret_payload_rejected if {
    secret := {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "fixture"}, "stringData": {"password": "fake"}}
    result := deny with input as object.union(empty_input, {"committed": [secret]})
    count(result) == 1
}

test_generated_secret_allowed if {
    secret := {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "fixture"}, "data": {"password": "fake"}}
    result := deny with input as object.union(empty_input, {"resources": [secret]})
    count(result) == 0
}

test_resource_replace_annotation_rejected if {
    resource := {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "fixture", "annotations": {"argocd.argoproj.io/sync-options": "Replace=true"}}}
    result := deny with input as object.union(empty_input, {"resources": [resource]})
    count(result) == 1
}
