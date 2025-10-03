Feature: Running external commands
  Scenario: Foreground execution of a simple sequence
    When I execute run_cmd with sequence "echo hello" in foreground
    Then run_cmd returns 0
    And the stderr log includes "$ echo hello"

  Scenario: Executing a Python snippet via adapter
    When I execute run_cmd with adapter "print('ok')"
    Then run_cmd returns 0
    And the stderr log includes "python -c"
