# make_test_image.ps1
# Renders a 1920x1080 mock "app screen" with KNOWN element bounding boxes,
# then downsizes a copy to 1280x720 (what the VLM will actually see).
# Output: shot_1920.png, shot_1280.png, labels.json
# ASCII only on purpose (Windows PowerShell 5.1 reads BOM-less UTF-8 as ANSI).

param([string]$OutDir = $PSScriptRoot)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$src = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'labels_source.json') | ConvertFrom-Json
$grid   = @($src.grid)
$danger = @($src.danger)
$tricky = @($src.tricky)

$W = 1920; $H = 1080
$bmp = New-Object System.Drawing.Bitmap $W, $H
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode    = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit

function New-Brush([int]$r, [int]$gg, [int]$b) {
  New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb($r, $gg, $b))
}
function New-Font([int]$size, [string]$style) {
  $fs = [System.Drawing.FontStyle]::Regular
  if ($style -eq 'bold') { $fs = [System.Drawing.FontStyle]::Bold }
  $unit = [System.Drawing.GraphicsUnit]::Pixel
  New-Object System.Drawing.Font 'Microsoft YaHei', $size, $fs, $unit
}

$bg      = New-Brush 242 245 250
$white   = New-Brush 255 255 255
$ink     = New-Brush 30 36 48
$muted   = New-Brush 122 132 153
$iconBg  = New-Brush 232 238 252
$dangerIcon = New-Brush 253 232 232
$greyInk = New-Brush 169 178 196
$greyBg  = New-Brush 244 246 250
$greyIcon = New-Brush 236 239 245
$borderPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(219, 227, 240)), 1

$g.Clear([System.Drawing.Color]::FromArgb(242, 245, 250))

# ---------- header ----------
$g.FillRectangle($white, 0, 0, $W, 72)
$g.DrawLine($borderPen, 0, 72, $W, 72)
$g.FillRectangle((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(59, 108, 246))), 48, 19, 34, 34)
$fBrand = New-Font 21 'bold'
$g.DrawString('CloudDesk', $fBrand, $ink, 96, 22)
$fNav = New-Font 17 'regular'
$nx = 260
foreach ($n in @('工作区', '任务', '报表', '成员')) {
  $br = if ($n -eq '工作区') { New-Brush 43 87 224 } else { $muted }
  $g.DrawString($n, $fNav, $br, $nx, 26)
  $nx += ($g.MeasureString($n, $fNav).Width + 6)
}
$g.FillEllipse((New-Brush 215 224 245), 1834, 17, 38, 38)

# ---------- title ----------
$fTitle = New-Font 22 'bold'
$fSub   = New-Font 15 'regular'
$g.DrawString('常用操作', $fTitle, $ink, 48, 108)
$g.DrawString('选择一个操作以继续（本页面仅用于 GUI 定位实验）', $fSub, $muted, 48, 142)

# ---------- grid of cards ----------
$elements = New-Object System.Collections.ArrayList
$fCard = New-Font 17 'regular'
$fSec  = New-Font 16 'bold'

$colW = 300; $rowH = 96; $gapX = 26; $gapY = 22
$ox = 48; $oy = 180
for ($i = 0; $i -lt $grid.Count; $i++) {
  $c = $i % 5; $r = [Math]::Floor($i / 5)
  $x = $ox + $c * ($colW + $gapX)
  $y = $oy + $r * ($rowH + $gapY)
  $rect = New-Object System.Drawing.Rectangle $x, $y, $colW, $rowH
  $g.FillRectangle($white, $rect)
  $g.DrawRectangle($borderPen, $rect)
  $g.FillRectangle($iconBg, ($x + 18), ($y + 31), 34, 34)
  $textY = $y + ($rowH - $g.MeasureString($grid[$i], $fCard).Height) / 2
  $g.DrawString($grid[$i], $fCard, $ink, ($x + 66), $textY)
  [void]$elements.Add([pscustomobject]@{
    id = ('btn-{0:d2}' -f ($i + 1)); label = $grid[$i];
    x = $x; y = $y; w = $colW; h = $rowH; clickable = $true
  })
}

# ---------- danger row (disabled) ----------
$secY = $oy + 4 * ($rowH + $gapY) + 16
$g.DrawString('危险操作（不可用）', $fSec, $muted, 48, $secY)
$dy = $secY + 32
for ($i = 0; $i -lt $danger.Count; $i++) {
  $x = $ox + $i * ($colW + $gapX)
  $rect = New-Object System.Drawing.Rectangle $x, $dy, $colW, 56
  $g.FillRectangle($greyBg, $rect)
  $g.DrawRectangle($borderPen, $rect)
  $g.FillRectangle($greyIcon, ($x + 18), ($dy + 15), 26, 26)
  $textY = $dy + (56 - $g.MeasureString($danger[$i], $fCard).Height) / 2
  $g.DrawString($danger[$i], $fCard, $greyInk, ($x + 58), $textY)
  [void]$elements.Add([pscustomobject]@{
    id = ('dis-{0:d2}' -f ($i + 1)); label = $danger[$i];
    x = $x; y = $dy; w = $colW; h = 56; clickable = $false
  })
}

# ---------- tricky row ----------
$ty = $dy + 56 + 46
$g.DrawString('提交确认', $fSec, $muted, 48, ($ty - 30))
for ($i = 0; $i -lt $tricky.Count; $i++) {
  $x = $ox + $i * ($colW + $gapX)
  $rect = New-Object System.Drawing.Rectangle $x, $ty, $colW, 56
  $g.FillRectangle($white, $rect)
  $g.DrawRectangle($borderPen, $rect)
  $textY = $ty + (56 - $g.MeasureString($tricky[$i], $fCard).Height) / 2
  $g.DrawString($tricky[$i], $fCard, $ink, ($x + 24), $textY)
  [void]$elements.Add([pscustomobject]@{
    id = ('tri-{0:d2}' -f ($i + 1)); label = $tricky[$i];
    x = $x; y = $ty; w = $colW; h = 56; clickable = $true
  })
}

# ---------- save 1920 ----------
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$p1920 = Join-Path $OutDir 'shot_1920.png'
$bmp.Save($p1920, [System.Drawing.Imaging.ImageFormat]::Png)

# ---------- downscale to 1280x720 ----------
$w2 = 1280; $h2 = 720
$small = New-Object System.Drawing.Bitmap $w2, $h2
$g2 = [System.Drawing.Graphics]::FromImage($small)
$g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g2.PixelOffsetMode   = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g2.DrawImage($bmp, (New-Object System.Drawing.Rectangle 0, 0, $w2, $h2))
$p1280 = Join-Path $OutDir 'shot_1280.png'
$small.Save($p1280, [System.Drawing.Imaging.ImageFormat]::Png)

$sx = $w2 / $W
$out = [pscustomobject]@{
  image_1920 = 'shot_1920.png'
  image_1280 = 'shot_1280.png'
  screen     = @($W, $H)
  model_input = @($w2, $h2)
  elements   = @($elements | ForEach-Object {
      [pscustomobject]@{
        id = $_.id; label = $_.label; clickable = $_.clickable
        x = $_.x; y = $_.y; w = $_.w; h = $_.h
        x1 = [Math]::Round($_.x * $sx, 1); y1 = [Math]::Round($_.y * $sx, 1)
        w1 = [Math]::Round($_.w * $sx, 1); h1 = [Math]::Round($_.h * $sx, 1)
      }
    })
}
$json = $out | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText((Join-Path $OutDir 'labels.json'), $json, (New-Object System.Text.UTF8Encoding($false)))

$g2.Dispose(); $small.Dispose(); $g.Dispose(); $bmp.Dispose()
Write-Output ("OK  elements=" + $elements.Count + "  ->  " + $OutDir)
