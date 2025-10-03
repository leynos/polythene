Feature: Script utility helpers
  Scenario: Creating a directory tree when missing
    Given a temporary workspace
    When I call ensure_directory for "data/cache"
    Then the path "data/cache" exists

  Scenario: Selecting a unique match
    Given a temporary workspace
    And the files "alpha.txt", "beta.txt" exist
    When I request a unique match for "alpha.txt"
    Then the unique match is "alpha.txt"
