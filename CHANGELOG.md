# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed
- Normalize numeric token handling in binding map generation
- Align backup worker FTP landing path with actual EMOS upload behavior (`/share/<SN>.txt`)
- Derive host list from HA entity state when `config.hosts` is empty

### Documentation
- Mark USS-P130_f5 (3.62.p5) as legacy backup exception due to unverified manual backup trigger syntax
- Clarify backup pipeline acceptance criteria across three layers:
  1. Integration/identity (binding map, runtime state)
  2. Worker ingestion (landing file presence, archive/metadata/diff)
  3. Device capability (known firmware support for backup commands)
- Recommend expressing results as `N/M synced + K waived legacy exception` when only legacy firmware devices are missing landing files
