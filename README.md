# Plot Stand Counter 🌱📊
### A Desktop GUI for Early-Season Stand Counts from RGB Orthomosaics

A lightweight **PySide6** desktop application for counting early-season crop stands (sunflower, corn, and other row crops) from large RGB GeoTIFF orthomosaics.

**Designed for:**
- Research plot trials
- Early sunflower stands assessment
- Early corn stand counts
- It will likely work for other crops as well, which might require to change some of the default parameters showing on the GUI.

**Windows executable build of the Plot Stand Counter tool**
- No Python installation required
- Download the zip from https://github.com/paulo-flores/plot_stand_count_exe/releases
- Extract it
- Run sunf_count_GUI.exe
- Tested on Windows 11 with sunflowers and corn images

---

## Features

### Plot-Based Stand Counting
- Define plots by clicking start/end points for each row
- Configurable number of rows per plot
- Configurable row spacing
- Optional fixed row length mode (e.g., standardized 20 ft strips)
- Adjustable row AOI width (ft)

### Detection & Adjustment
- Excess Green (ExG) vegetation segmentation
- Otsu thresholding inside row AOI
- Morphological cleanup
- Connected components plant detection
- Cluster/double detection heuristic
- Raw and adjusted counts

### Metrics Computed

**Per Row:**
- Row length (ft)
- Adjusted plant count
- Raw plant count
- Plants per foot

**Per Plot:**
- Total adjusted plants
- Total raw plants
- Plants per acre (adjusted + raw)
- Plot area (ft²)

### Large GeoTIFF Support
- Built-in pyramid (overview) creation
- Option to build overviews in-place or on a copy *(copy recommended)*
- Smooth zoom and pan for large mosaics

### Output Files
- `rows.csv` — row-level data
- `plots.csv` — plot-level summaries
- `annotated_overview.png`
- Individual plot images: `plot_####_raw.png` and `plot_####_annot.png`

> ⚠️ The original TIFF is **never modified** by annotations.

---

## Workflow

### 1. Open GeoTIFF
- Go to **File → Open GeoTIFF**
- Set your **Output Folder**

### 2. Enable Pyramids *(Recommended)*
- Check **Ensure overviews (pyramids) on open**
- Select **Build overviews on a COPY** *(recommended)*

This ensures smooth navigation on large images.

### 3. Configure Plot Parameters
- Rows per plot
- Row spacing (inches)
- Row AOI width (ft)
- Fixed row length (optional)
- Detection parameters (area, circularity, cluster factor)

### 4. Digitize a Plot
Click to define row endpoints:
- Row 1 → start, end
- Row 2 → start, end
- … After the final required click → preview computes automatically

### 5. Review & Accept

| Shortcut | Action |
|----------|--------|
| `a` | Accept & Save |
| `d` | Discard |
| `ESC` | Discard preview |

Additional controls:
- **Show Preview (Left)** — visually inspect detection
- **Mouse wheel** — zoom
- **Right-click drag** — pan
- **Reset View** — return to full overview

---

## Detection Method

### Vegetation Extraction
1. Compute Excess Green index:
   ```
   ExG = 2G - R - B
   ```
2. Otsu thresholding within the row AOI
3. Morphological closing
4. Remove small objects
5. Connected components labeling

### Cluster Adjustment
For each row:
- Compute median blob area
- If `blob_area > cluster_factor × median`:
  - Flag as cluster
  - Assign a size multiplier (capped)
- Adjusted counts sum multipliers per row

---

## Example Applications
- Early sunflower and corn stand counts
- Multi-row research plots
- Fixed-length sampling strips (e.g., 15 ft, 20 ft, 30 ft)
- Any row length between the 1st and 2nd mouse click on the when "Fixed row length (ft)" is set to 0

---

## Citation / Acknowledgements

If you use this tool in your research, please consider citing or acknowledging the source. Contributions and issues are welcome via GitHub.
