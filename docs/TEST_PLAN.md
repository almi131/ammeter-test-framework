# Test plan

Each case maps to a pytest function in `tests/` (`python -m pytest -v`). `tests/test_cross_platform.py::test_plan_maps_to_existing_tests` checks that every name below exists.

| TC | Area | Test | File |
|---|---|---|---|
| TC-01 | Greenlee emulator returns a float | `test_tc01_greenlee_measurement` | `test_ammeter_communication.py` |
| TC-02 | ENTES emulator returns a float | `test_tc02_entes_measurement` | `test_ammeter_communication.py` |
| TC-03 | CIRCUTOR emulator returns a float | `test_tc03_circutor_measurement` | `test_ammeter_communication.py` |
| TC-04 | Connection refused is a typed error | `test_tc04_connection_failure` | `test_ammeter_communication.py` |
| TC-05 | Slow reply is a timeout error | `test_tc05_communication_timeout` | `test_ammeter_communication.py` |
| TC-06 | Invalid reply is a parse/no-reply error | `test_tc06_invalid_emulator_response` | `test_ammeter_communication.py` |
| TC-07 | One API for all meters | `test_tc07_unified_api_for_all_ammeters` | `test_unified_api.py` |
| TC-08 | Same result schema for every meter | `test_tc08_consistent_result_format` | `test_unified_api.py` |
| TC-09 | Unknown meter is rejected | `test_tc09_unsupported_ammeter` | `test_unified_api.py` |
| TC-10 | Configurable measurement count | `test_tc10_measurement_count` | `test_sampling.py` |
| TC-11 | Configurable total duration | `test_tc11_sampling_duration` | `test_sampling.py` |
| TC-12 | Configurable sampling frequency | `test_tc12_sampling_frequency` | `test_sampling.py` |
| TC-13 | Combined count/duration/frequency | `test_tc13_combined_sampling_configuration` | `test_sampling.py` |
| TC-14 | Invalid sampling parameters | `test_tc14_invalid_sampling_parameters` | `test_sampling.py` |
| TC-15 | Timing precision | `test_tc15_scheduled_times_use_injected_clock`, `test_tc15_real_clock_within_tolerance` | `test_sampling.py` |
| TC-16 | Mean | `test_tc16_mean_calculation` | `test_statistics.py` |
| TC-17 | Median (odd and even) | `test_tc17_median_odd_and_even` | `test_statistics.py` |
| TC-18 | Standard deviation | `test_tc18_standard_deviation` | `test_statistics.py` |
| TC-19 | Minimum and maximum | `test_tc19_minimum_and_maximum` | `test_statistics.py` |
| TC-20 | Statistical edge cases | `test_tc20_statistical_edge_cases` | `test_statistics.py` |
| TC-21 | Save results | `test_tc21_save_test_results` | `test_result_management.py` |
| TC-22 | Unique run id | `test_tc22_unique_test_run_id` | `test_result_management.py` |
| TC-23 | Metadata stored | `test_tc23_metadata_storage` | `test_result_management.py` |
| TC-24 | Historical retrieval | `test_tc24_historical_result_retrieval` | `test_result_management.py` |
| TC-25 | Historical comparison | `test_tc25_historical_result_comparison` | `test_result_management.py` |
| TC-26 | Partial measurement failure | `test_tc26_partial_measurement_failure` | `test_error_handling.py` |
| TC-27 | Complete measurement failure | `test_tc27_complete_measurement_failure` | `test_error_handling.py` |
| TC-28 | Compare meters | `test_tc28_compare_ammeter_measurements` | `test_accuracy.py` |
| TC-29 | Relative accuracy | `test_tc29_relative_accuracy` | `test_accuracy.py` |
| TC-30 | Measurement consistency | `test_tc30_measurement_consistency` | `test_accuracy.py` |
| TC-31 | Visualization | `test_tc31_measurement_visualization` | `test_visualization.py` |
| TC-32 | Error simulation | `test_tc32_error_simulation`, `test_tc32_disabled_simulation_keeps_valid_samples` | `test_error_simulation.py` |
| TC-33 | Load configuration | `test_tc33_load_configuration` | `test_configuration.py` |
| TC-34 | Invalid configuration | `test_tc34_invalid_configuration` | `test_configuration.py` |
| TC-35 | End-to-end workflow | `test_tc35_complete_measurement_workflow` | `test_e2e.py` |
| TC-36 | Several meters in one run | `test_tc36_multiple_ammeter_execution` | `test_e2e.py` |
| TC-37 | End-to-end failure recovery | `test_tc37_e2e_failure_recovery` | `test_e2e.py` |
| TC-38 | Ubuntu is in the CI matrix and runs the suite | `test_tc38_ubuntu_ci` | `test_cross_platform.py` |
| TC-39 | Windows is in the CI matrix and runs the suite | `test_tc39_windows_ci` | `test_cross_platform.py` |
| TC-40 | macOS is in the CI matrix and runs the suite | `test_tc40_macos_ci` | `test_cross_platform.py` |

TC-38..40 check that `.github/workflows/tests.yml` lists the OS and runs pytest, `main.py` and `examples/run_tests.py`. The actual pass/fail per OS is the GitHub Actions run history.

Beyond the numbered cases: `tests/test_archive.py` (run archive), `tests/test_winners.py` (winner selection), `tests/test_performance.py` (timing), and regression tests in `tests/test_sampling.py` and `tests/test_statistics.py` (half-open window, CI/outliers).
