# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
-

### Changed
-

### Fixed
-

## [1.7.0] - 2026-03-26

### Added
- Search illustrations command (`/pixiv search {keyword}`)
- Search users command (`/pixiv searchuser {keyword}`)
- Translated tag support with `translate=true/false` option
- Search options: sort, target, duration, page, limit
- Search results display with illust preview image
- User search results with recent works list

### Changed
- Improved emoji reaction handler with duplicate detection
- Cleaned up debug logging in emoji_reaction.py

## [1.6.0] - 2026-03-26

### Added
- Unique mode optimization: track sent image IDs, auto-expand scan range
- Multi-image support: auto forward messages for >3 images
- Image quality settings (original/medium/small)
- Config management command (`/pixiv config`)
- DNS status display in `/pixiv dns`
- Cache now command for immediate caching

### Changed
- Refactored main.py into submodules
- Use event.message_str for full command arguments

### Fixed
- Fixed idle cache count parameter not working
- Fixed @ user mention handling
- Fixed share command debug logging

## [1.0.0] - 2026-03-24

### Added
- Unified cache pool with metadata filtering
- R-18 group chat filtering with admin config
- Ugoira support with PIL and ffmpeg dual rendering
- Idle cache queue and unique random mode
- Group blocked tags management
- Image quality configuration

### Fixed
- Fixed cache, config management and random selection issues

## [0.3.0] - 2026-03-23

### Added
- Unified cache pool for cross-filter reuse
- Metadata-based filtering (tags, author, R-18)
- R-18 group chat filtering (admin configurable)
- illustID cache auto-add to random pool
- Token-free operations for share/r18/@username
- ffmpeg fallback for ugoira rendering
- Emoji reaction toggle
- Debug logging and SSL optimization
- Accesser and pixez-flutter integration

### Fixed
- Fixed share config blocked by token check

## [0.2.0] - 2026-03-23

### Added
- Emoji mapping and cache mechanism
- Collection sharing feature
- `/pixiv random share` command
- Message filter for commands

## [0.1.0] - 2026-03-23

### Added
- Initial release
- User login with refresh_token
- Illust detail query
- Artist detail query
- Random bookmark collection
- Built-in cache and rate limiting
- PixEz DNS proxy support
