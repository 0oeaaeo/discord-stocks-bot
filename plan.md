# Discord Stock Exchange - Enhancement Plan (COMPLETED)

## 1. Short-Selling Lockup (Security) - ✅ DONE
*   **Implementation:** Added 1-hour lockup check in `close_short` and status indicator in `shorts`.

## 2. Feature: Dynamic Company News (Individual Events) - ✅ DONE
*   **Implementation:** Added `market_news` table and background task in `Economy` to trigger news based on activity spikes.

## 3. Feature: Automated Limit Orders - ✅ DONE
*   **Implementation:** Added `limit_orders` table and `$limit buy/sell` commands. Automated execution in `Economy` price update loop.

## 4. Feature: Achievements & Titles - ✅ DONE
*   **Implementation:** Added `achievements` table and `$achievements` command. Implemented "First Millionaire" auto-unlock.
