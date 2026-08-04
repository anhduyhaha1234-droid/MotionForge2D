param(
    [ValidateSet("READY", "BLOCKED", "DECISION", "TEST")]
    [string]$Type = "TEST",
    [string]$Task = "",
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
$shell = New-Object -ComObject WScript.Shell

switch ($Type) {
    "READY" {
        $title = "MotionForge2D - Sẵn sàng review"
        $body = "Hermes đã hoàn thành roadmap và kiểm tra cuối.`n`nMở Codex và gửi:`nReview tổng thể MotionForge2D và bàn giao bản sử dụng được."
        $icon = 64
    }
    "BLOCKED" {
        $title = "MotionForge2D - Autopilot cần Codex"
        $body = "Hermes đang bị chặn tại $Task.`n`n$Message`n`nMở Codex và gửi:`nKiểm tra blocker Autopilot và tiếp tục."
        $icon = 48
    }
    "DECISION" {
        $title = "MotionForge2D - Cần quyết định"
        $body = "Hermes cần quyết định tại $Task.`n`n$Message`n`nMở session MF-Autopilot-Main hoặc gọi Codex."
        $icon = 32
    }
    default {
        $title = "MotionForge2D - Popup test"
        $body = "Popup Autopilot hoạt động.`n`nKhi thấy popup BLOCKED hoặc READY, hãy mở Codex và gửi đúng câu được hiển thị."
        $icon = 64
    }
}

# 0 seconds means the popup remains until the user acknowledges it.
[void]$shell.Popup($body, 0, $title, $icon)
