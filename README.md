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

- **✨ New v0.3.0**
**Auto-Grid Row Generation**
Rows can now be automatically propagated across replicated plots using forward and backward grid segments, reducing manual clicking during plot setup.

**Inter-Segment Gap Support**
Users can define alleys or spacing between replicated plots, allowing more accurate representation of experimental layouts.

**Parallel Processing**
Row detection and counting are now processed in parallel, significantly improving preview and computation speed.

**Interactive Plot Analytics**
Accepted plots now include dynamic chart popups:
- Hover over a plot to view stand counts.
- Double-click a plot to pin the chart for closer inspection.

**Segment-Level Visualization**
Auto-grid plots now generate separate charts for each segment, providing cleaner comparisons between replicated areas.

**Cleaner Overview Visualization**
The interface now removes clutter from the overview image. Detection counts are displayed in charts instead of being printed on the imagery.

**Improved Interface Layout**
The parameter panel is now scrollable, preventing UI compression when the window is resized or maximized.

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
## Row Input Modes
The Stand Count Tool provides three methods for defining the rows used in stand counting. Each mode is designed for a different type of field layout or workflow.

 **_Manual Rows Mode_**
_How it works:_
The user manually defines each row within a plot by clicking the start and end points of every row on the orthomosaic image.
  1. Select **Manual rows** from the *Row input mode* dropdown.
  2. Set the **Rows per plot** value.
  3. For each row:
   * Click the **start point** of the row.
   * Click the **end point** of the row.
  4. After all rows are defined, the tool will compute the preview automatically.
  5. Review the detection results and either:
   * **Accept / Save** the plot, or
   * **Discard** and redraw.
  **Example**
    For a 4-row plot:
    * 8 clicks are required (2 clicks per row).

**_Auto-Parallel Rows Mode_**
_How it works:_
The user draws **one reference row**, and the tool automatically generates additional rows on both sides using the specified **row spacing**.
  1. Select **Auto-parallel rows** mode.
  2. Click the **start and end point of a reference row**.
  3. Specify:
   * **Rows on side A**
   * **Rows on side B**
  4. Optionally enable **Include reference row**.
  5. The tool generates the remaining rows automatically.

  **Example**
  If:
    * Rows on side A = 2
    * Rows on side B = 2
    * Include reference row = enabled
  The tool generates **5 rows total**.

_**Auto-Grid Rows Mode**_
_How it works:_
The user draws **one reference row**, and the tool automatically generates:
  * Parallel rows across the plot width
  * Additional **segments forward and backward** along the row direction

Can be used to create a **grid of replicated plots**.

  1. Select **Auto-grid rows** mode.
  2. Click the **start and end point of a reference row**.
  3. Define rows across the plot:
     * **Rows on side A**
     * **Rows on side B**
  4. Define replicated segments:
     * **Segments forward**
     * **Segments backward**
  5. Set the **segment spacing**, or enable:
     * **Use row length as segment spacing**
  6. Optionally define an **inter-segment gap** to account for alleys between plots.
    **Example**
      If:
        * Rows on side A = 2
        * Rows on side B = 2
        * Include reference row = enabled
        * Segments forward = 2
        * Segments backward = 2
      The tool generates:
        * **5 rows per segment**
        * **5 segments total**
        Total rows analyzed = **25 rows**.



### Step 4 — Compute preview

After selecting rows, click: Compute Preview

The tool will:
  Extract the plot region
  Detect plants
  Estimate clusters
  Display detection results

You can inspect the detection results before saving.

### Step 5 — Inspect detection results

Click: Show Preview

This displays:
  detected plants
  flagged clusters
  row boundaries
  plant counts

### Step 6 — Accept or discard
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
  
