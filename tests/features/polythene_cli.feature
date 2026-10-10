Feature: Polythene CLI interactions
  Scenario: Exporting an image successfully
    Given a clean store directory
    And UUID generation returns "uuid-abc"
    And image export succeeds
    When I run the CLI with arguments "pull busybox --store {store}"
    Then the CLI exits with code 0
    And stdout equals "uuid-abc"
    And the rootfs directory "uuid-abc" exists

  Scenario: Reusing a locally built image without a registry pull
    Given a clean store directory
    And UUID generation returns "uuid-local"
    And Podman already records the image "localhost/example:latest"
    When I run the CLI with arguments "pull localhost/example:latest --store {store}"
    Then the CLI exits with code 0
    And stdout equals "uuid-local"
    And the rootfs directory "uuid-local" exists
    And Podman probed for "localhost/example:latest" but never pulled

  Scenario: Invoking the CLI via python -m polythene
    Given a clean store directory
    And UUID generation returns "uuid-module"
    And image export succeeds
    When I run the module CLI with arguments "pull busybox --store {store}"
    Then the CLI exits with code 0
    And stdout equals "uuid-module"
    And the rootfs directory "uuid-module" exists

  Scenario: Executing with a missing rootfs
    Given a clean store directory
    When I run the CLI with arguments "exec missing --store {store} -- true"
    Then the CLI exits with code 1
    And stderr contains "No such UUID rootfs"

  Scenario: Executing via proot avoids login shell side effects
    Given a clean store directory
    And the rootfs "uuid-proot" exists
    And proot execution is stubbed
    When I run the CLI with arguments "exec uuid-proot --store {store} -- true"
    Then the CLI exits with code 0
    And proot ran without requesting a login shell
