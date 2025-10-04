Feature: Running external commands
  Scenario: Foreground execution of a simple command
    When I execute run_cmd with command "echo hello" in foreground
    Then run_cmd returns 0
    And the stderr log includes "echo hello"

  Scenario: Executing a Python snippet via adapter
    When I execute run_cmd with adapter "print('ok')"
    Then run_cmd returns 0
    And the stderr log includes "python -c"

  Scenario: Rejecting an empty command string
    When I execute run_cmd with no command in foreground
    Then run_cmd raises a ValueError containing "Command must contain at least one token"

  Scenario: Rejecting an invalid command object
    When I execute run_cmd with an invalid command object
    Then run_cmd raises a TypeError containing "plumbum invocation or pipeline"
