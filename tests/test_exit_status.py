"""
A failed deploy must exit non-zero (CAPIP-6601).

These run the real subprocess calls against a fake `kubectl` placed first on
PATH, so they exercise the same failure path a broken manifest takes in CI
without needing a cluster or AWS credentials.
"""
import os
import stat
import sys
from subprocess import CalledProcessError

import pytest

from k8sdeploy import main as main_module
from k8sdeploy.k8sdeploy import KubernetesDeploy


API_VARS = {
    "deploy_type": "api",
    "target_app_name": "demo-app",
    "target_namespace": "demo",
    "secret": {},
    "configmap": {"KEY": "value"},
    "create_service": True,
    "create_ingress": False,
    "ecr_account_id": "000000000000",
    "target_rollout_timeout_seconds": 1800,
}


@pytest.fixture
def fake_kubectl(tmp_path, monkeypatch):
    """
    Install a fake kubectl. `fail_on` is a substring of the argv that makes it
    exit 1 (as kubectl does for a rejected manifest); every call is logged.
    """
    call_log = tmp_path / "calls.log"

    def install(fail_on=None, apply_output="deployment.apps/demo-app configured"):
        script = tmp_path / "kubectl"
        failure_check = ""
        if fail_on:
            failure_check = (
                f'case "$*" in *"{fail_on}"*) '
                'echo "error: simulated kubectl failure" >&2; exit 1;; esac\n'
            )
        script.write_text(
            "#!/bin/sh\n"
            f'echo "$*" >> "{call_log}"\n'
            f"{failure_check}"
            f'echo "{apply_output}"\n'
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        return call_log

    return install


def make_deploy(monkeypatch, **overrides):
    """A KubernetesDeploy with AWS and template rendering stubbed out."""
    deploy = KubernetesDeploy.__new__(KubernetesDeploy)
    deploy.stack = "dev"
    deploy.vars = API_VARS | overrides
    deploy.rollout_restart = False
    monkeypatch.setattr(deploy, "wait_api_availability", lambda: None)
    monkeypatch.setattr(deploy, "checkAWSToken", lambda account: None)
    monkeypatch.setattr(deploy, "load_template", lambda name, data: f"kind: {name}\n")
    return deploy


def logged_calls(call_log):
    return call_log.read_text().splitlines() if call_log.exists() else []


def test_failed_apply_of_non_deployment_manifest_raises(fake_kubectl, monkeypatch):
    fake_kubectl(fail_on="apply")
    deploy = make_deploy(monkeypatch)
    with pytest.raises(CalledProcessError):
        deploy.load_deploy("configmap", "apply")


def test_failed_apply_of_deployment_raises(fake_kubectl, monkeypatch):
    fake_kubectl(fail_on="apply")
    deploy = make_deploy(monkeypatch)
    with pytest.raises(CalledProcessError):
        deploy.load_deploy("deployment", "apply")


def test_rendered_manifest_is_removed_even_on_failure(fake_kubectl, monkeypatch, tmp_path):
    fake_kubectl(fail_on="apply")
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    deploy = make_deploy(monkeypatch)
    with pytest.raises(CalledProcessError):
        deploy.load_deploy("secret", "apply")
    assert list(tmp_path.glob("*.yaml")) == []


def test_failed_apply_stops_the_deploy(fake_kubectl, monkeypatch):
    call_log = fake_kubectl(fail_on="apply")
    deploy = make_deploy(monkeypatch)
    with pytest.raises(CalledProcessError):
        deploy.deploy_objects()
    # namespace was the first apply and it failed, so nothing after it ran
    assert len(logged_calls(call_log)) == 1


def test_rollout_that_never_becomes_ready_fails(fake_kubectl, monkeypatch):
    """A bad image applies cleanly; only rollout status sees it."""
    call_log = fake_kubectl(fail_on="rollout status")
    deploy = make_deploy(monkeypatch)
    with pytest.raises(CalledProcessError):
        deploy.deploy_objects()
    assert any(
        "rollout status deployment.apps/demo-app -n demo --timeout=1800s" in call
        for call in logged_calls(call_log)
    )


def test_failed_rollout_restart_raises(fake_kubectl, monkeypatch):
    fake_kubectl(fail_on="rollout restart", apply_output="deployment.apps/demo-app unchanged")
    deploy = make_deploy(monkeypatch)
    with pytest.raises(CalledProcessError):
        deploy.deploy_objects()


def test_rollout_wait_can_be_disabled(fake_kubectl, monkeypatch):
    call_log = fake_kubectl(fail_on="rollout status")
    deploy = make_deploy(monkeypatch, target_rollout_timeout_seconds=0)
    deploy.deploy_objects()
    assert not any("rollout status" in call for call in logged_calls(call_log))


def test_delete_tolerates_resources_already_gone(fake_kubectl, monkeypatch):
    call_log = fake_kubectl()
    deploy = make_deploy(monkeypatch)
    deploy.deploy_objects(action="delete")
    calls = logged_calls(call_log)
    assert calls and all("--ignore-not-found" in call for call in calls)
    assert not any("rollout status" in call for call in calls)


def test_successful_deploy_waits_for_rollout(fake_kubectl, monkeypatch):
    call_log = fake_kubectl()
    deploy = make_deploy(monkeypatch)
    deploy.deploy_objects()
    assert "rollout status" in logged_calls(call_log)[-1]


def test_main_exits_non_zero_when_kubectl_fails(monkeypatch):
    class FailingDeploy:
        def __init__(self, *args):
            pass

        def deploy_objects(self, **kwargs):
            raise CalledProcessError(1, ["kubectl", "apply", "-f", "manifest.yaml"])

    monkeypatch.setattr(main_module, "KubernetesDeploy", FailingDeploy)
    monkeypatch.setattr(sys, "argv", ["k8sdeploy", "-s", "dev", "-e", "000000000000"])
    assert main_module.main() == 1


def test_main_exits_zero_on_success(monkeypatch):
    class PassingDeploy:
        def __init__(self, *args):
            pass

        def deploy_objects(self, **kwargs):
            pass

    monkeypatch.setattr(main_module, "KubernetesDeploy", PassingDeploy)
    monkeypatch.setattr(sys, "argv", ["k8sdeploy", "-s", "dev", "-e", "000000000000"])
    assert main_module.main() == 0


@pytest.mark.parametrize("tags_string, expected", [
    ("a=1, b=2", {"a": "1", "b": "2"}),
    ("a:1,b:2", {"a": "1", "b": "2"}),
])
def test_parse_tags_accepts_either_separator(tags_string, expected):
    deploy = KubernetesDeploy.__new__(KubernetesDeploy)
    assert deploy.parse_tags(tags_string, "ingress_tags") == expected


def test_parse_tags_names_the_variable_when_malformed():
    deploy = KubernetesDeploy.__new__(KubernetesDeploy)
    with pytest.raises(ValueError, match="ingress_additional_tags"):
        deploy.parse_tags("waf-type=exception-alb,not-a-tag", "ingress_additional_tags")
