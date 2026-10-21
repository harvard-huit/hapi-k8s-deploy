"""
The opt-in HorizontalPodAutoscaler (target_hpa_*).

Templates are rendered for real from the package defaults, so these check the
manifests kubectl would receive. Deploy-flow tests reuse the fake kubectl from
test_exit_status.
"""
import pytest
import yaml

from k8sdeploy.k8sdeploy import KubernetesDeploy
from test_exit_status import fake_kubectl, logged_calls, make_deploy  # noqa: F401


APP_VARS = {
    "deploy_type": "api",
    "target_app_name": "demo-app",
    "target_namespace": "demo",
    "target_app_port": 8080,
    "target_image_tag": "1.0.0",
    "target_stack": "dev",
    "stack": "dev",
    "secret": {},
    "configmap": {},
    "ingress_additional_tags": "",
}

HPA_VARS = {
    "target_hpa_enabled": True,
    "target_hpa_max_replicas": 10,
    "target_set_resources": True,
}


def resolved_vars(**overrides):
    """App vars merged over the package defaults, as __deploy_data__ does."""
    deploy = KubernetesDeploy.__new__(KubernetesDeploy)
    deploy.default_path = KubernetesDeploy.__init__.__globals__["os"].path.dirname(
        KubernetesDeploy.__init__.__globals__["__file__"])
    data = APP_VARS | overrides
    data = deploy.load_defaults("default_vars.yml", data) | data
    return deploy, deploy.set_hpa_data(data)


def render(template, **overrides):
    deploy, data = resolved_vars(**overrides)
    return yaml.safe_load(deploy.load_template(template, data))


def test_disabled_by_default_keeps_target_replica_count():
    deployment = render("deployment", target_replica_count=4)
    assert deployment["spec"]["replicas"] == 4


def test_hpa_targets_the_app_container_cpu_by_default():
    hpa = render("hpa", **HPA_VARS, target_replica_count=3)
    assert hpa["spec"]["scaleTargetRef"] == {"apiVersion": "apps/v1", "kind": "Deployment", "name": "demo-app"}
    assert hpa["spec"]["minReplicas"] == 3 and hpa["spec"]["maxReplicas"] == 10
    assert hpa["spec"]["metrics"] == [{
        "type": "ContainerResource",
        "containerResource": {"name": "cpu", "container": "demo-app",
                              "target": {"type": "Utilization", "averageUtilization": 70}},
    }]
    assert hpa["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "k8sdeploy"
    assert "behavior" not in hpa["spec"]


def test_custom_metrics_and_behavior_pass_through():
    """hapi-ais-llm's request-rate HPA, expressed in k8s_vars."""
    pods_metric = {"type": "Pods", "pods": {"metric": {"name": "gunicorn_requests_per_second"},
                                            "target": {"type": "AverageValue", "averageValue": "2"}}}
    behavior = {"scaleDown": {"stabilizationWindowSeconds": 300,
                              "policies": [{"type": "Percent", "value": 10, "periodSeconds": 60}]}}
    hpa = render("hpa", **HPA_VARS | {"target_hpa_max_replicas": 60}, target_hpa_min_replicas=20, target_hpa_cpu_utilization=50,
                 target_hpa_memory_utilization=80, target_hpa_metrics=[pods_metric],
                 target_hpa_behavior=behavior)
    metrics = hpa["spec"]["metrics"]
    assert [m.get("containerResource", {}).get("name") for m in metrics[:2]] == ["cpu", "memory"]
    assert metrics[0]["containerResource"]["target"]["averageUtilization"] == 50
    assert metrics[2] == pods_metric
    assert hpa["spec"]["behavior"] == behavior
    assert hpa["spec"]["minReplicas"] == 20 and hpa["spec"]["maxReplicas"] == 60


def test_custom_metrics_alone_need_no_resources():
    hpa = render("hpa", target_hpa_enabled=True, target_hpa_max_replicas=5, target_hpa_cpu_utilization="",
                 target_hpa_metrics=[{"type": "Pods", "pods": {"metric": {"name": "x"},
                                                              "target": {"type": "AverageValue", "averageValue": "1"}}}])
    assert [m["type"] for m in hpa["spec"]["metrics"]] == ["Pods"]


@pytest.mark.parametrize("live, expected", [(7, 7), (0, 0), (None, 3)])
def test_enabled_deployment_keeps_live_replicas(live, expected):
    """A deploy must not undo a scale-up; a new Deployment starts at the HPA minimum."""
    deployment = render("deployment", **HPA_VARS, target_replica_count=9, target_hpa_min_replicas=3,
                        target_live_replica_count=live)
    assert deployment["spec"]["replicas"] == expected


@pytest.mark.parametrize("overrides, message", [
    ({"target_hpa_max_replicas": ""}, "target_hpa_max_replicas is required"),
    ({"target_hpa_min_replicas": 5, "target_hpa_max_replicas": 2}, "<= target_hpa_max_replicas"),
    ({"target_hpa_min_replicas": 0}, "1 <= target_hpa_min_replicas"),
    ({"target_set_resources": False}, "target_hpa_cpu_utilization needs container requests"),
    ({"target_hpa_cpu_utilization": "", "target_hpa_metrics": []}, "HPA has no metric"),
])
def test_bad_hpa_settings_fail_before_deploy(overrides, message):
    with pytest.raises(ValueError, match=message):
        resolved_vars(**(HPA_VARS | overrides))


def test_enabled_deploy_applies_hpa_after_deployment(fake_kubectl, monkeypatch):
    call_log = fake_kubectl()
    deploy = make_deploy(monkeypatch, target_hpa_enabled=True)
    deploy.deploy_objects()
    calls = logged_calls(call_log)
    get = next(i for i, c in enumerate(calls) if c.startswith("get deployment demo-app"))
    applies = [i for i, c in enumerate(calls) if c.startswith("apply")]
    # namespace, configmap, deployment, hpa, service: the live count is read before the deployment
    assert get < applies[2] and len(applies) == 5
    assert not any(c.startswith("delete hpa") for c in calls)


def test_disabled_deploy_removes_only_its_own_hpa(fake_kubectl, monkeypatch):
    call_log = fake_kubectl()
    deploy = make_deploy(monkeypatch)
    deploy.deploy_objects()
    deletes = [c for c in logged_calls(call_log) if c.startswith("delete hpa")]
    assert deletes == ["delete hpa -n demo -l app=demo-app,app.kubernetes.io/managed-by=k8sdeploy --ignore-not-found"]


def test_delete_action_removes_hpa_without_reading_replicas(fake_kubectl, monkeypatch):
    call_log = fake_kubectl()
    deploy = make_deploy(monkeypatch, target_hpa_enabled=True)
    deploy.deploy_objects(action="delete")
    calls = logged_calls(call_log)
    assert any(c.startswith("delete hpa") for c in calls)
    assert not any(c.startswith("get deployment") for c in calls)
