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

approved_herdr := {
    "apiVersion": "argoproj.io/v1alpha1", "kind": "Application",
    "metadata": {"name": "herdr", "namespace": "argocd"},
    "spec": {
        "project": "default",
        "source": {"repoURL": "https://github.com/benkim0414/homelab.git", "targetRevision": "main", "path": "herdr"},
        "destination": {"server": "https://kubernetes.default.svc", "namespace": "herdr"},
        "syncPolicy": {"automated": {"enabled": true, "prune": false, "selfHeal": false, "allowEmpty": false}}
    }
}

test_approved_herdr_auto_sync_allowed if {
    result := deny with input as object.union(empty_input, {"applications": [approved_herdr]})
    count(result) == 0
}

test_other_app_cannot_borrow_herdr_auto_sync if {
    other := object.union(approved_herdr, {"metadata": {"name": "hermes", "namespace": "argocd"}})
    result := deny with input as object.union(empty_input, {"applications": [other]})
    count(result) == 1
}

test_herdr_prune_self_heal_and_empty_sync_are_rejected if {
    every setting in ["prune", "selfHeal", "allowEmpty"] {
        changed := object.union(approved_herdr.spec.syncPolicy.automated, {setting: true})
        spec := object.union(approved_herdr.spec, {"syncPolicy": {"automated": changed}})
        candidate := object.union(approved_herdr, {"spec": spec})
        result := deny with input as object.union(empty_input, {"applications": [candidate]})
        count(result) == 1
    }
}

test_herdr_auto_sync_cannot_target_other_source if {
    source := object.union(approved_herdr.spec.source, {"path": "hermes"})
    spec := object.union(approved_herdr.spec, {"source": source})
    candidate := object.union(approved_herdr, {"spec": spec})
    result := deny with input as object.union(empty_input, {"applications": [candidate]})
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
