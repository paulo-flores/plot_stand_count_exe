# Plot Stand Counter 🌱📊
### A Desktop GUI for Early-Season Stand Counts from RGB Orthomosaics

A lightweight **PySide6** desktop application for counting early-season crop stands (sunflower, corn, and other row crops) from large RGB GeoTIFF orthomosaics.

**Designed for:**
- Research plot trials and field sample assessments
- Early sunflower stands assessment
- Early corn stand counts
- It will likely work for other crops as well, such as sugar beets and dry beans, but it might require to change some of the default parameters showing on the GUI.

**Windows executable build of the Plot Stand Counter tool**
- No Python installation required
- Download the zip from https://github.com/paulo-flores/plot_stand_count_exe/releases
- Extract it
- Run stand_count_GUI_update
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
> Updated Windows EXE build of the Plot Stand Counter tool.

### New in version v0.2.0:
- Added auto-parallel row generation mode
- User can select one reference row and generate parallel rows using row spacing
- Added side A / side B row generation controls
- Added optional reference-row inclusion
- Added global perpendicular offset control
- Continued support for manual row mode, tidy CSV outputs, and GeoTIFF overview creation

---

## Workflow

### 1. Open GeoTIFF
- Go to **File → Open GeoTIFF**
- Set your **Output Folder**

### 2. Enable Pyramids *(Recommended)*
- Check **Ensure overviews (pyramids) on open**
- Select **Build overviews on a COPY** *(recommended)*

This ensures smooth navigation on large images.

### 3. Row Selection Modes
The tools supports two row selection modes
### Manual Row Mode
### Procedure
1. Set:
Row input mode → Manual rows

2. Specify:
Rows per plot

3. For each row:
- Click row start
- Click row end

4. Repeat until all rows are defined.

Example:
For a 4-row plot:8 clicks total

### Auto-Parallel Row Mode (New Feature)
Auto-parallel mode speeds up plot setup by generating multiple rows automatically.
The user only selects one reference row, and the tool generates parallel rows using the row spacing.

### How it works?
Auto-Parallel Row Mode (New Feature)

Auto-parallel mode speeds up plot setup by generating multiple rows automatically.

1. Select:
Row input mode → Auto-parallel rows

2. Define:
Parameter	                  Description
Rows on side A                Number of rows generated on one side
Rows on side B	               Rows generated on the other side
Include reference row	      Include the clicked row in the plot
Row spacing	                  Distance between rows
Global offset	               Adjust alignment if rows are slightly shifted

Example
If you set:
- Rows side A = 5
- Rows side B = 5
- Include reference row = true
- Total rows counted: 11 rows
- Only two clicks are required.

### Step 3 — Compute preview

After selecting rows, click:

Compute Preview

The tool will:

Extract the plot region

Detect plants

Estimate clusters

Display detection results

You can inspect the detection results before saving.

### Step 4 — Inspect detection results

Click:

Show Preview

This displays:

detected plants

flagged clusters

row boundaries

plant counts

### Step 5 — Accept or discard
Keyboard shortcuts:

Key	      Action
A      	Accept plot
D	      Discard plot
ESC      Cancel preview

When accepted: data are written to CSV
               annotated images are saved
               plot is drawn on the overview map

### Output Files
1) rows.csv : Contains row-level data.

Column	               Description
plot_id	               Plot number
row_index	            Row number
row_label	            Row identifier
row_spacing_in	         Row spacing
row_len_ft	            Row length
row_adj	               Adjusted plant count
row_raw	               Raw plant count
row_clusters	         Number of clusters
plants_per_ft_adj	      Plants per foot

2) plots.csv: Contains plot-level statistics.

Column	                  Description
plot_id	                  Plot number
input_mode	               Manual or auto-parallel
n_rows	                  Number of rows counted
row_spacing_in	            Row spacing
plot_area_ft2	            Plot area
plot_sum_adj	            Adjusted plant count
plot_sum_raw	            Raw plant count
plot_plants_per_acre_adj	Plants per acre (adjusted)
plot_plants_per_acre_raw	Plants per acre (raw)

3) plots folder
Each plot produces two images: plot_0001_raw.png
                               plot_0001_annot.png

The annotated image shows: plant detections, cluster flags, row boundaries, row counts

annotated_overview.png: Overview of the entire field with all saved plots drawn.

### Tips for Best Results
Use high resolution imagery: Recommended 1–3 cm/pixel

Ensure good lighting conditions: images captured under consistent lighting, minimal shadows, produce better detection results.

Adjust cluster factor if needed

Large plants or overlapping plants may be detected as clusters.

The cluster factor parameter controls when plants are considered multiples. Typical values: 1.2 – 1.6

### Troubleshooting
Image appears pixelated: This usually means the image lacks pyramids.
                         Enable: ensure overviews when loading the GeoTIFF.

Rows appear slightly misaligned: Adjust "Global offset". This shifts all generated rows together.

Plants are over-counted: Increase "Min area" or reduce "Cluster factor"

### Citation

If you use this tool in research or publications, please cite the repository.

https://github.com/paulo-flores/plot_stand_count_exe
  
