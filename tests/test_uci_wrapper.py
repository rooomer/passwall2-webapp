import pytest
import subprocess
from unittest.mock import patch, MagicMock

from bot import uci_wrapper as uci

def test_safe():
    """Test shell escaping function."""
    assert uci._safe("safe_string") == "safe_string"
    assert uci._safe("inject'; rm -rf /;") == "'inject'\"'\"'; rm -rf /;'"

@patch("subprocess.run")
def test_run_list_command(mock_run):
    """Test _run with a list command (shell=False)."""
    mock_result = MagicMock()
    mock_result.stdout = "output text\n"
    mock_run.return_value = mock_result

    res = uci._run(["echo", "test"])
    assert res == "output text"
    mock_run.assert_called_with(["echo", "test"], capture_output=True, text=True, timeout=10)

@patch("subprocess.run")
def test_run_timeout(mock_run):
    """Test standard command timeout handling."""
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["sleep", "20"], timeout=10)
    
    res = uci._run(["sleep", "20"])
    
    # Should swallow the exception and return empty string
    assert res == ""

@patch("bot.uci_wrapper._run")
def test_uci_get(mock_irun):
    """Test uci get command formatting."""
    mock_irun.return_value = "1"
    res = uci.uci_get("passwall2", "@global[0]", "enabled")
    
    assert res == "1"
    mock_irun.assert_called_with(["uci", "-q", "get", "passwall2.@global[0].enabled"])

@patch("bot.uci_wrapper._run")
def test_uci_set(mock_irun):
    """Test uci set command formatting."""
    uci.uci_set("passwall2", "@global[0]", "node", "US_Node")
    mock_irun.assert_called_with(["uci", "set", "passwall2.@global[0].node=US_Node"])

@patch("subprocess.run")
def test_uci_batch(mock_run):
    """Test uci_batch multi-command execution (Fork Bomb fix)."""
    ops = [
        "set passwall2.@global[0].node=Node1",
        "set passwall2.@global[0].enabled=1",
        "commit passwall2"
    ]
    uci.uci_batch(ops)
    
    expected_input = "\n".join(ops) + "\n"
    mock_run.assert_called_with(
        ["uci", "batch"],
        input=expected_input,
        capture_output=True, text=True, timeout=15
    )

@patch("bot.uci_wrapper._run")
def test_ping_node_valid(mock_irun):
    """Test ping network utility with valid inputs."""
    mock_irun.return_value = "64 bytes from 1.1.1.1: icmp_seq=1 ttl=58 time=14.5 ms"
    
    res = uci.ping_node("1.1.1.1", ping_type="icmp")
    
    assert res == "14.5"
    mock_irun.assert_called_with(["ping", "-c", "1", "-W", "1", "1.1.1.1"], timeout=5)

def test_ping_node_inject():
    """Test ping vulnerability scanning (Fix #1: shell injection protection)."""
    # Attempting shell injection should be rejected by regex
    res = uci.ping_node("1.1.1.1; cat /etc/shadow")
    assert res == ""
    
    res_port = uci.ping_node("1.1.1.1", port="80; rm -rf /")
    assert res_port == ""

@patch("bot.uci_wrapper._run")
def test_restore_backup_safe(mock_irun):
    """Test backup restore filename validation."""
    # Attempt Path Traversal
    res_bad = uci.restore_backup("../../../etc/shadow")
    assert res_bad is False
    
    # Valid name
    res_ok = uci.restore_backup("/tmp/passwall2-2305011400-backup.tar.gz")
    assert res_ok is True
