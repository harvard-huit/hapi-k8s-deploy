"""
Which EKS cluster a deploy targets: the stack's default generation, or the
app's target_eks_cluster (a generation or a full cluster name).
"""
import sys

import pytest

from k8sdeploy import main as main_module
from k8sdeploy.k8sdeploy import (
    CLUSTER_NAME_FORMATS,
    STACK_CLUSTER_GENERATION,
    EksUpateConfig,
    KubernetesDeploy,
    resolve_cluster_name,
)
from test_exit_status import fake_kubectl, logged_calls


@pytest.mark.parametrize("stack, expected", [
    ("sand", "adexk8s-eks-cluster-sand"),
    ("dev", "adexk8s-eks-cluster-dev"),
    ("test", "adexk8s-test-eks-cluster"),
    ("stage", "adexk8s-eks-cluster-stage"),
    ("prod", "adexk8s-eks-cluster-prod"),
])
def test_stack_default_generation(stack, expected):
    assert resolve_cluster_name(stack) == expected
    assert resolve_cluster_name(stack, {}) == expected


def test_every_stack_default_is_a_known_generation():
    assert set(STACK_CLUSTER_GENERATION.values()) <= set(CLUSTER_NAME_FORMATS)


@pytest.mark.parametrize("target, expected", [
    ("gen1", "adexk8s-eks-cluster-dev"),
    ("gen2", "adexk8s-dev-eks-cluster"),
    ("my-scratch-cluster", "my-scratch-cluster"),
])
def test_app_override(target, expected):
    assert resolve_cluster_name("dev", {"target_eks_cluster": target}) == expected


@pytest.mark.parametrize("empty", [None, ""])
def test_empty_override_uses_the_stack_default(empty):
    assert resolve_cluster_name("test", {"target_eks_cluster": empty}) == "adexk8s-test-eks-cluster"


def test_unknown_generation_is_rejected_not_used_as_a_name():
    with pytest.raises(ValueError, match="unknown cluster generation 'gen9'"):
        resolve_cluster_name("dev", {"target_eks_cluster": "gen9"})


def test_stack_without_a_default_needs_an_override():
    with pytest.raises(ValueError, match="no default cluster generation"):
        resolve_cluster_name("qa")
    assert resolve_cluster_name("qa", {"target_eks_cluster": "gen2"}) == "adexk8s-qa-eks-cluster"


def write_vars(tmp_path, text):
    var_file = tmp_path / "target_vars.yml"
    var_file.write_text(text)
    return str(var_file)


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["k8sdeploy", *argv])
    status = main_module.main()
    return status, capsys.readouterr()


def test_print_cluster_name_uses_the_vars_file(tmp_path, monkeypatch, capsys):
    var_file = write_vars(tmp_path, "target_app_name: demo\ntarget_eks_cluster: gen2\n")
    status, out = run_main(monkeypatch, capsys, "-s", "dev", "-f", var_file, "--print-cluster-name")
    assert status == 0 and out.out == "adexk8s-dev-eks-cluster\n"


def test_print_cluster_name_without_a_vars_file(tmp_path, monkeypatch, capsys):
    status, out = run_main(monkeypatch, capsys, "-s", "test", "-f", str(tmp_path / "missing.yml"), "-c")
    # only the name on stdout, so $(k8sdeploy ... -c) is safe to use
    assert status == 0 and out.out == "adexk8s-test-eks-cluster\n"


def test_print_cluster_name_fails_on_unknown_generation(tmp_path, monkeypatch, capsys):
    var_file = write_vars(tmp_path, "target_eks_cluster: gen9\n")
    status, out = run_main(monkeypatch, capsys, "-s", "dev", "-f", var_file, "-c")
    assert status == 1 and out.out == "" and "gen9" in out.err


def test_update_eks_config_targets_the_override(tmp_path, monkeypatch):
    var_file = write_vars(tmp_path, "target_eks_cluster: gen2\n")
    monkeypatch.setattr("k8sdeploy.k8sdeploy.boto3.client", lambda service: None)
    assert EksUpateConfig("dev", "20.168.125.97", var_file).cluster_name == "adexk8s-dev-eks-cluster"
    assert EksUpateConfig("dev", "20.168.125.97").cluster_name == "adexk8s-eks-cluster-dev"


def test_main_passes_the_vars_file_to_update_eks_config(tmp_path, monkeypatch):
    seen = {}

    class RecordingUpdate:
        def __init__(self, *args):
            seen["args"] = args

        def update_config(self, action):
            pass

    var_file = write_vars(tmp_path, "target_eks_cluster: gen2\n")
    monkeypatch.setattr(main_module, "EksUpateConfig", RecordingUpdate)
    monkeypatch.setattr(sys, "argv", ["k8sdeploy", "-s", "dev", "-f", var_file, "-u", "20.168.125.97"])
    assert main_module.main() == 0
    assert seen["args"] == ("dev", "20.168.125.97", var_file)


def kubeconfig_check(fake_kubectl, context_cluster, cluster_name="adexk8s-test-eks-cluster"):
    call_log = fake_kubectl(apply_output=context_cluster)
    deploy = KubernetesDeploy.__new__(KubernetesDeploy)
    deploy.cluster_name = cluster_name
    deploy.check_kubeconfig_cluster()
    return logged_calls(call_log)


def test_kubeconfig_on_the_resolved_cluster_passes(fake_kubectl):
    calls = kubeconfig_check(fake_kubectl, "arn:aws:eks:us-east-1:328144961263:cluster/adexk8s-test-eks-cluster")
    assert calls == ["config view --minify -o jsonpath={.contexts[0].context.cluster}"]


def test_kubeconfig_on_another_cluster_fails(fake_kubectl):
    with pytest.raises(Exception, match="update-kubeconfig --name adexk8s-test-eks-cluster"):
        kubeconfig_check(fake_kubectl, "arn:aws:eks:us-east-1:328144961263:cluster/adexk8s-eks-cluster-test")


def test_kubeconfig_not_from_update_kubeconfig_only_warns(fake_kubectl, capsys):
    kubeconfig_check(fake_kubectl, "kind-local")
    assert "could not confirm" in capsys.readouterr().err


@pytest.mark.parametrize("stack, environment", [("test", "Test"), ("sand", "Development")])
def test_environment_tag(stack, environment):
    deploy = KubernetesDeploy.__new__(KubernetesDeploy)
    deploy.stack = stack
    assert deploy.get_tag_data({})["environment"] == environment


class FakeSts:
    def __init__(self, account):
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account}


@pytest.mark.parametrize("stack, account, consistent", [
    ("test", "328144961263", True),
    ("test", "000000000000", False),
    ("prod", "000000000000", True),
    ("prod", "328144961263", False),
])
def test_test_stack_is_a_nonprod_account(monkeypatch, stack, account, consistent):
    """ecr_account is the nonprod account: nonprod stacks must run in it, prod stacks outside it."""
    monkeypatch.setattr("k8sdeploy.k8sdeploy.boto3.client", lambda service: FakeSts(account))
    deploy = KubernetesDeploy.__new__(KubernetesDeploy)
    deploy.stack = stack
    if consistent:
        deploy.checkAWSToken("328144961263")
    else:
        with pytest.raises(Exception, match="not consistent"):
            deploy.checkAWSToken("328144961263")
