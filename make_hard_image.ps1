# make_hard_image.ps1
# Renders a HARD variant: small fonts, tight spacing, low contrast,
# partial occlusion, and near-identical labels.
# Output: shot_1920.png, shot_1280.png, labels.json  (in .\hard)

param(
  [string]$OutDir = (Join-Path $PSScriptRoot 'hard'),
  [int]$FontSize = 12,
  [switch]$NoIcon
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$rel = Split-Path $OutDir -Leaf

$src = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'hard\labels_source.json') | ConvertFrom-Json
$grid = @($src.grid); $similar = @($src.similar); $tiny = @($src.tiny)

$W = 1920; $H = 1080
$bmp = New-Object System.Drawing.Bitmap $W, $H
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit

function Br([int]$r, [int]$gg, [int]$b) { New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb($r, $gg, $b)) }
function Fn([int]$size, [string]$s) {
  $st = [System.Drawing.FontStyle]::Regular
  if ($s -eq 'bold') { $st = [System.Drawing.FontStyle]::Bold }
  $u = [System.Drawing.GraphicsUnit]::Pixel
  New-Object System.Drawing.Font 'Microsoft YaHei', $size, $st, $u
}

$white = Br 255 255 255
$panel = Br 250 250 252
$ink = Br 90 99 112        # low contrast on purpose
$ink2 = Br 120 128 140
$line = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(232, 235, 240)), 1
$fBtn = Fn $FontSize 'regular'
$fTiny = Fn ([Math]::Max(7, $FontSize - 3)) 'regular'

$g.Clear([System.Drawing.Color]::FromArgb(246, 247, 250))

# 顶部工具栏（高密度、小图标块）
$g.FillRectangle($white, 0, 0, $W, 56)
$g.DrawLine($line, 0, 56, $W, 56)
for ($i = 0; $i -lt 18; $i++) {
  $x = 24 + $i * 40
  $g.FillRectangle((Br 226 231 240), $x, 16, 24, 24)
}

$elements = New-Object System.Collections.ArrayList

# 主网格：6 列 × 4 行，240x54，间距 10
$colW = 240; $rowH = 54; $gapX = 10; $gapY = 10; $ox = 40; $oy = 96
for ($i = 0; $i -lt $grid.Count; $i++) {
  $c = $i % 6; $r = [Math]::Floor($i / 6)
  $x = $ox + $c * ($colW + $gapX); $y = $oy + $r * ($rowH + $gapY)
  $rect = New-Object System.Drawing.Rectangle $x, $y, $colW, $rowH
  $g.FillRectangle($white, $rect)
  $g.DrawRectangle($line, $rect)
  if (-not $NoIcon) { $g.FillRectangle((Br 214 222 235), ($x + 10), ($y + 17), 20, 20) }
  $tx = if ($NoIcon) { $x + 12 } else { $x + 38 }
  $ty = $y + ($rowH - $g.MeasureString($grid[$i], $fBtn).Height) / 2
  $g.DrawString($grid[$i], $fBtn, $ink, $tx, $ty)
  [void]$elements.Add([pscustomobject]@{
    id = ('g-{0:d2}' -f ($i + 1)); label = $grid[$i]
    x = $x; y = $y; w = $colW; h = $rowH; clickable = $true
  })
}

# 相似按钮区（低对比、无边框）
$sy = $oy + 4 * ($rowH + $gapY) + 26
$g.DrawString('操作', $fBtn, $ink2, 40, ($sy - 22))
for ($i = 0; $i -lt $similar.Count; $i++) {
  $x = $ox + $i * ($colW + $gapX); $y = $sy
  $rect = New-Object System.Drawing.Rectangle $x, $y, $colW, 40
  $g.FillRectangle($panel, $rect)
  $g.DrawRectangle($line, $rect)
  $ty = $y + (40 - $g.MeasureString($similar[$i], $fBtn).Height) / 2
  $g.DrawString($similar[$i], $fBtn, $ink2, ($x + 12), $ty)
  [void]$elements.Add([pscustomobject]@{
    id = ('s-{0:d2}' -f ($i + 1)); label = $similar[$i]
    x = $x; y = $y; w = $colW; h = 40; clickable = $true
  })
}

# 小字按钮（极难）
$tinyX = 40 + 3 * ($colW + $gapX)
for ($i = 0; $i -lt $tiny.Count; $i++) {
  $x = $tinyX + $i * 90; $y = $sy + 4
  $rect = New-Object System.Drawing.Rectangle $x, $y, 80, 32
  $g.FillRectangle($white, $rect)
  $g.DrawRectangle($line, $rect)
  $g.DrawString($tiny[$i], $fTiny, $ink2, ($x + 14), ($y + 8))
  [void]$elements.Add([pscustomobject]@{
    id = ('t-{0:d2}' -f ($i + 1)); label = $tiny[$i]
    x = $x; y = $y; w = 80; h = 32; clickable = $true
  })
}

# 半透明遮挡层：盖住右下方一部分按钮，制造"看不清"
$overlay = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(168, 238, 240, 245))
$g.FillRectangle($overlay, 1180, 250, 700, 220)
$g.DrawString('加载中…', (Fn 14 'regular'), (Br 170 178 190), 1220, 280)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$p1920 = Join-Path $OutDir 'shot_1920.png'
$bmp.Save($p1920, [System.Drawing.Imaging.ImageFormat]::Png)

$w2 = 1280; $h2 = 720
$small = New-Object System.Drawing.Bitmap $w2, $h2
$g2 = [System.Drawing.Graphics]::FromImage($small)
$g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$g2.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$g2.DrawImage($bmp, (New-Object System.Drawing.Rectangle 0, 0, $w2, $h2))
$small.Save((Join-Path $OutDir 'shot_1280.png'), [System.Drawing.Imaging.ImageFormat]::Png)

$sx = $w2 / $W
$out = [pscustomobject]@{
  image_1920 = "$rel/shot_1920.png"
  image_1280 = "$rel/shot_1280.png"
  screen = @($W, $H)
  model_input = @($w2, $h2)
  elements = @($elements | ForEach-Object {
      [pscustomobject]@{
        id = $_.id; label = $_.label; clickable = $_.clickable
        x = $_.x; y = $_.y; w = $_.w; h = $_.h
        x1 = [Math]::Round($_.x * $sx, 1); y1 = [Math]::Round($_.y * $sx, 1)
        w1 = [Math]::Round($_.w * $sx, 1); h1 = [Math]::Round($_.h * $sx, 1)
      }
    })
}
[System.IO.File]::WriteAllText((Join-Path $OutDir 'labels.json'), ($out | ConvertTo-Json -Depth 6),
  (New-Object System.Text.UTF8Encoding($false)))

$g2.Dispose(); $small.Dispose(); $g.Dispose(); $bmp.Dispose()
Write-Output ("OK hard elements=" + $elements.Count + " -> " + $OutDir)
