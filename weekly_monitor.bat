@echo off
REM Weekly Campaign Monitor Batch File
REM Run this weekly to monitor and update your Google Ads campaigns

echo Starting Weekly Campaign Monitor...
echo Date: %date% %time%
echo.

REM Set your customer ID here
set CUSTOMER_ID=866-851-6809

REM Set your merchant ID here
set MERCHANT_ID=5561430685

REM Run the monitor in dry-run mode first (to see what would happen)
echo Running in DRY-RUN mode first...
python src\weekly_campaign_monitor.py ^
    --customer %CUSTOMER_ID% ^
    --label-index 0 ^
    --prefix "PMax Feed" ^
    --daily-budget 5.0 ^
    --merchant-id %MERCHANT_ID% ^
    --target-languages "it" ^
    --target-countries "IT" ^
    --feed-label "nl" ^
    --min-impressions 100 ^
    --min-conversions 0 ^
    --days-back 7 ^
    --auto-pause-empty ^
    --dry-run

echo.
echo ========================================
echo DRY-RUN completed. Review the output above.
echo.
echo To apply changes, run the same command without --dry-run
echo and add --apply true
echo.
echo Example:
echo python src\weekly_campaign_monitor.py --customer %CUSTOMER_ID% --label-index 0 --prefix "PMax Feed" --daily-budget 5.0 --merchant-id %MERCHANT_ID% --target-languages "it" --target-countries "IT" --feed-label "nl" --min-impressions 100 --min-conversions 0 --days-back 7 --auto-pause-empty --apply true
echo.
pause



