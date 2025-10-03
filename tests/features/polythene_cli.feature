Feature: Polythene CLI interactions
  Scenario: Exporting an image successfully
    Given a clean store directory
    And UUID generation returns "uuid-abc"
    And image export succeeds
    When I run the CLI with arguments "pull busybox --store {store}"
    Then the CLI exits with code 0
    And stdout equals "uuid-abc"
    And the rootfs directory "uuid-abc" exists

  Scenario: Executing with a missing rootfs
    Given a clean store directory
    When I run the CLI with arguments "exec missing --store {store} -- true"
    Then the CLI exits with code 1
    And stderr contains "No such UUID rootfs"
