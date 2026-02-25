# Sunf_count_GUI.py
# PySide6 GUI for sunflower plot stand counting from GeoTIFF (with optional auto-pyramids/overviews).
#
# NEW in this version:
# - Optional "Ensure overviews (pyramids)" integrated in the GUI
# - Option to build overviews IN PLACE or on a COPY in the output folder (recommended)
# - "Build overviews now" button (in case you want to do it after opening)
# - Overview status indicator (Yes/No)
#
# Notes:
# - Building overviews modifies the target GeoTIFF. Using "COPY" avoids changing the original.
# - If overviews cannot be built (permissions/lock), the tool continues without them.

import csv
import math
import time
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple

import numpy as np
import cv2
import rasterio
from rasterio.windows import Window
from rasterio.enums import Resampling

from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_objects, closing, disk
from skimage.measure import regionprops, label

from PySide6.QtCore import Qt, QRectF, QThread, Signal, QObject, QPointF
from PySide6.QtGui import QPixmap, QImage, QAction, QPainter, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QHBoxLayout, QVBoxLayout, QFormLayout, QGroupBox, QPushButton, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QLineEdit, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QSizePolicy, QSplitter
)

# ===================== DEFAULT SETTINGS =====================
DEFAULT_USE_BANDS_RGB = (1, 2, 3)

DEFAULT_MAX_OVERVIEW_DIM = 4500
DEFAULT_OVERVIEW_RESAMPLING = rasterio.enums.Resampling.average

# Overviews build defaults
DEFAULT_OVERVIEW_LEVELS = (2, 4, 8, 16, 32, 64)

# Plot geometry defaults
DEFAULT_ROWS_PER_PLOT = 4
DEFAULT_ROW_SPACING_IN = 30.0
DEFAULT_ROW_AOI_WIDTH_FT = 0.8

# Segmentation tuning defaults
DEFAULT_MIN_AREA_PX = 40
DEFAULT_CLOSING_RADIUS_PX = 3
DEFAULT_CIRCULARITY_MIN = 0.20

# Cluster/double heuristic defaults
DEFAULT_BASELINE_STAT = "median"   # "median" or "mean"
DEFAULT_DOUBLE_FACTOR = 1.6
DEFAULT_MAX_CLUSTER_MULTIPLIER = 4
DEFAULT_USE_ADJUSTED_COUNTS = True

# Interaction / measurement defaults
DEFAULT_SHOW_LIVE_LENGTH = True
DEFAULT_FIXED_ROW_LENGTH_FT = 20.0   # 0 = free end-point clicking

# Drawing colors (BGR for OpenCV)
CLUSTER_COLOR = (0, 0, 255)      # red
NORMAL_COLOR  = (0, 255, 255)    # yellow
AOI_COLOR     = (0, 255, 0)      # green

FT_TO_M = 0.3048
ACRE_FT2 = 43560.0
# ===========================================================


@dataclass
class PreviewResult:
    crop_bgr: np.ndarray
    vis_bgr: np.ndarray
    row_raw: List[int]
    row_adj: List[int]
    row_clusters: List[int]
    plot_sum_raw: int
    plot_sum_adj: int
    row_polys_full: List[np.ndarray]
    all_pts_full: np.ndarray


@dataclass
class ViewState:
    transform: object
    hbar: int
    vbar: int
    scene_rect: QRectF


# -------------------- Overviews helpers --------------------
def has_overviews(tif_path: Path, band: int = 1) -> bool:
    try:
        with rasterio.open(str(tif_path)) as ds:
            ovs = ds.overviews(band)
        return ovs is not None and len(ovs) > 0
    except Exception:
        return False


def build_overviews_inplace(
    tif_path: Path,
    levels: Tuple[int, ...] = DEFAULT_OVERVIEW_LEVELS,
    resampling: Resampling = Resampling.average
) -> None:
    # Writes overviews into the GeoTIFF
    with rasterio.open(str(tif_path), "r+") as ds:
        ds.build_overviews(levels, resampling=resampling)
        ds.update_tags(ns="rio_overview", resampling=str(resampling))
        ds.update_tags(ns="rio_overview", levels=",".join(map(str, levels)))
        ds.update_tags(ns="rio_overview", built=time.strftime("%Y-%m-%d %H:%M:%S"))
# ----------------------------------------------------------


def percentile_stretch_to_uint8(rgb: np.ndarray) -> np.ndarray:
    """rgb float (H,W,3) -> uint8 BGR for OpenCV"""
    out = np.zeros_like(rgb, dtype=np.float32)
    for c in range(3):
        chan = rgb[..., c].astype(np.float32)
        p2, p98 = np.percentile(chan, (2, 98))
        if p98 > p2:
            chan = (chan - p2) / (p98 - p2)
        else:
            chan = chan * 0.0
        out[..., c] = np.clip(chan, 0, 1)
    out = (out * 255).astype(np.uint8)
    return out[..., ::-1]  # RGB->BGR


def read_rgb_window(ds: rasterio.io.DatasetReader, window: Window, bands=(1, 2, 3)) -> np.ndarray:
    r_i, g_i, b_i = bands
    r = ds.read(r_i, window=window).astype(np.float32)
    g = ds.read(g_i, window=window).astype(np.float32)
    b = ds.read(b_i, window=window).astype(np.float32)
    return np.dstack([r, g, b])


def exg_index(rgb: np.ndarray) -> np.ndarray:
    """Excess Green index normalized to 0..1 (simple, stable for early vegetation)."""
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    exg = 2 * g - r - b
    exg = exg - np.nanmin(exg)
    denom = np.nanmax(exg) - np.nanmin(exg)
    if denom > 0:
        exg = exg / denom
    return exg


def circularity(area: float, perimeter: float) -> float:
    if perimeter <= 0:
        return 0.0
    return 4.0 * math.pi * float(area) / (float(perimeter) ** 2)


def build_rect_from_line(p_start_xy, p_end_xy, width_px: float) -> np.ndarray:
    """
    Rectangle centered on the line from start->end with given width (px).
    Returns 4x2 polygon corners in (x,y) order.
    """
    p1 = np.array(p_start_xy, dtype=np.float32)
    p2 = np.array(p_end_xy, dtype=np.float32)
    v = p2 - p1
    n = np.linalg.norm(v)
    if n < 1e-6:
        raise ValueError("Row line too short.")
    u = v / n
    perp = np.array([-u[1], u[0]], dtype=np.float32)
    half_w = width_px / 2.0

    p1_left = p1 + perp * half_w
    p1_right = p1 - perp * half_w
    p2_left = p2 + perp * half_w
    p2_right = p2 - perp * half_w
    return np.vstack([p1_left, p2_left, p2_right, p1_right])


def polygon_mask(h: int, w: int, poly_xy: np.ndarray) -> np.ndarray:
    mask = np.zeros((h, w), dtype=np.uint8)
    pts = np.round(poly_xy).astype(np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(mask, [pts], 1)
    return mask.astype(bool)


def count_plants_components(
    rgb_crop: np.ndarray,
    mask_crop: np.ndarray,
    min_area_px: int,
    closing_radius_px: int,
    circularity_min: float
):
    """
    Connected components with circularity filter (stable for ~7 DAE sunflower).
    """
    exg = exg_index(rgb_crop)
    vals = exg[mask_crop]
    if vals.size < 50:
        return []

    try:
        thr = threshold_otsu(vals)
    except Exception:
        thr = np.median(vals)

    veg = (exg > thr) & mask_crop

    if closing_radius_px > 0:
        veg = closing(veg, disk(closing_radius_px))

    veg = remove_small_objects(veg, min_size=int(min_area_px))

    lab = label(veg)
    props = regionprops(lab)

    kept = []
    for p in props:
        if p.area < min_area_px:
            continue
        circ = circularity(p.area, p.perimeter if p.perimeter > 0 else 1.0)
        if circ >= circularity_min:
            kept.append(p)
    return kept


def compute_baseline_area(areas: List[float], stat: str) -> Optional[float]:
    if len(areas) == 0:
        return None
    if stat.lower() == "mean":
        return float(np.mean(areas))
    return float(np.median(areas))


def estimate_multiplier(area: float, baseline: Optional[float], factor: float, max_mult: int) -> Tuple[bool, int]:
    """Flag cluster if area > factor*baseline. Return (is_cluster, multiplier)."""
    if baseline is None or baseline <= 0:
        return False, 1
    if area <= factor * baseline:
        return False, 1
    est = int(np.round(area / baseline))
    est = max(2, est)
    est = min(est, max_mult)
    return True, est


def clamp_window(col_off, row_off, width, height, max_w, max_h):
    col_off = int(max(col_off, 0))
    row_off = int(max(row_off, 0))
    width = int(min(width, max_w - col_off))
    height = int(min(height, max_h - row_off))
    return col_off, row_off, width, height


def draw_poly(img_bgr: np.ndarray, poly_xy: np.ndarray, color, thickness=1):
    pts = np.round(poly_xy).astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(img_bgr, [pts], True, color, thickness)


def convex_hull_poly(points_xy: np.ndarray):
    pts = np.round(np.array(points_xy, dtype=np.float32)).astype(np.int32)
    pts = pts.reshape((-1, 1, 2))
    return cv2.convexHull(pts)


def bgr_to_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    return QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()


def ensure_outputs(out_dir: Path) -> Tuple[Path, Path, Path, Path]:
    plots_dir = out_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    rows_csv = out_dir / "rows.csv"
    plots_csv = out_dir / "plots.csv"
    annotated_path = out_dir / "annotated_overview.png"

    if not rows_csv.exists():
        with open(rows_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "plot_id", "row_index",
                "row_spacing_in",
                "row_len_ft",
                "row_adj", "row_raw", "row_clusters",
                "plants_per_ft_adj"
            ])

    if not plots_csv.exists():
        with open(plots_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "plot_id",
                "n_rows",
                "row_spacing_in",
                "plot_area_ft2",
                "plot_sum_adj", "plot_sum_raw",
                "plot_plants_per_acre_adj", "plot_plants_per_acre_raw",
                "plot_image_annot", "plot_image_raw"
            ])

    return plots_dir, rows_csv, plots_csv, annotated_path


def next_plot_id_from_plots_csv(plots_csv: Path) -> int:
    try:
        with open(plots_csv, "r", newline="") as f:
            return max(1, sum(1 for _ in f))
    except Exception:
        return 1


class PreviewWorker(QObject):
    finished = Signal(object)   # PreviewResult
    failed = Signal(str)

    def __init__(
        self,
        tif_path: str,
        points_ovr: List[Tuple[int, int]],
        n_rows: int,
        scale: float,
        px_size: float,
        row_aoi_width_ft: float,
        bands_rgb: Tuple[int, int, int],
        min_area_px: int,
        closing_radius_px: int,
        circ_min: float,
        baseline_stat: str,
        double_factor: float,
        max_cluster_mult: int,
        use_adjusted: bool,
    ):
        super().__init__()
        self.tif_path = tif_path
        self.points_ovr = points_ovr
        self.n_rows = n_rows
        self.scale = scale
        self.px_size = px_size
        self.row_aoi_width_ft = row_aoi_width_ft
        self.bands_rgb = bands_rgb
        self.min_area_px = min_area_px
        self.closing_radius_px = closing_radius_px
        self.circ_min = circ_min
        self.baseline_stat = baseline_stat
        self.double_factor = double_factor
        self.max_cluster_mult = max_cluster_mult
        self.use_adjusted = use_adjusted

    def run(self):
        try:
            row_width_px = (self.row_aoi_width_ft * FT_TO_M) / self.px_size

            row_polys_full = []
            for rr in range(self.n_rows):
                p_start = np.array((self.points_ovr[2 * rr][0] / self.scale,
                                    self.points_ovr[2 * rr][1] / self.scale), dtype=np.float32)
                p_end = np.array((self.points_ovr[2 * rr + 1][0] / self.scale,
                                  self.points_ovr[2 * rr + 1][1] / self.scale), dtype=np.float32)
                row_polys_full.append(build_rect_from_line(p_start, p_end, row_width_px))

            all_pts = np.vstack(row_polys_full)

            minx = int(np.floor(all_pts[:, 0].min())) - 25
            maxx = int(np.ceil(all_pts[:, 0].max())) + 25
            miny = int(np.floor(all_pts[:, 1].min())) - 25
            maxy = int(np.ceil(all_pts[:, 1].max())) + 25

            with rasterio.open(self.tif_path) as ds:
                col_off, row_off, width, height = clamp_window(
                    minx, miny, (maxx - minx + 1), (maxy - miny + 1), ds.width, ds.height
                )
                window = Window(col_off=col_off, row_off=row_off, width=width, height=height)
                rgb_crop = read_rgb_window(ds, window, bands=self.bands_rgb)

            crop_bgr = percentile_stretch_to_uint8(rgb_crop)
            vis = crop_bgr.copy()

            row_raw, row_adj, row_clusters = [], [], []

            for idx, poly_full in enumerate(row_polys_full, start=1):
                poly_crop = poly_full.copy()
                poly_crop[:, 0] -= col_off
                poly_crop[:, 1] -= row_off

                mask = polygon_mask(height, width, poly_crop)
                props = count_plants_components(
                    rgb_crop, mask,
                    min_area_px=self.min_area_px,
                    closing_radius_px=self.closing_radius_px,
                    circularity_min=self.circ_min
                )

                areas = [p.area for p in props]
                baseline = compute_baseline_area(areas, self.baseline_stat)

                raw_count = len(props)
                cluster_count = 0
                adjusted_count = 0

                draw_poly(vis, poly_crop, AOI_COLOR, 1)

                for p in props:
                    cy, cx = p.centroid
                    a = float(p.area)
                    is_cluster, mult = estimate_multiplier(a, baseline, self.double_factor, self.max_cluster_mult)
                    if is_cluster:
                        cluster_count += 1
                    adjusted_count += (mult if self.use_adjusted else 1)

                    color = CLUSTER_COLOR if is_cluster else NORMAL_COLOR
                    cv2.circle(vis, (int(round(cx)), int(round(cy))), 2, color, -1)
                    if is_cluster:
                        cv2.putText(vis, f"x{mult}",
                                    (int(round(cx)) + 4, int(round(cy)) - 4),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, CLUSTER_COLOR, 2, cv2.LINE_AA)

                bx, by = int(np.min(poly_crop[:, 0])), int(np.min(poly_crop[:, 1]))
                cv2.putText(vis, f"R{idx}: adj={adjusted_count} raw={raw_count} cl={cluster_count}",
                            (bx + 5, by + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

                row_raw.append(raw_count)
                row_adj.append(adjusted_count)
                row_clusters.append(cluster_count)

            plot_sum_raw = int(np.sum(row_raw))
            plot_sum_adj = int(np.sum(row_adj))

            res = PreviewResult(
                crop_bgr=crop_bgr,
                vis_bgr=vis,
                row_raw=row_raw,
                row_adj=row_adj,
                row_clusters=row_clusters,
                plot_sum_raw=plot_sum_raw,
                plot_sum_adj=plot_sum_adj,
                row_polys_full=row_polys_full,
                all_pts_full=all_pts
            )
            self.finished.emit(res)

        except Exception as e:
            self.failed.emit(str(e))


class ZoomPanView(QGraphicsView):
    pointClicked = Signal(int, int)
    mouseMovedImg = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._image_w = 1
        self._image_h = 1

        self._panning = False
        self._pan_start = None
        self.setDragMode(QGraphicsView.NoDrag)

        self.capture_clicks = True

    def set_capture_clicks(self, enabled: bool):
        self.capture_clicks = enabled

    def reset_view_fit(self):
        if self.scene() is None:
            return
        self.resetTransform()
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def get_view_state(self) -> ViewState:
        return ViewState(
            transform=self.transform(),
            hbar=self.horizontalScrollBar().value(),
            vbar=self.verticalScrollBar().value(),
            scene_rect=self.sceneRect()
        )

    def set_view_state(self, st: ViewState):
        self.setTransform(st.transform)
        self.horizontalScrollBar().setValue(st.hbar)
        self.verticalScrollBar().setValue(st.vbar)

    def setPixmapFirstTime(self, pix: QPixmap):
        if self.scene() is None:
            self.setScene(QGraphicsScene(self))
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(pix)
        self._image_w = pix.width()
        self._image_h = pix.height()
        self.scene().setSceneRect(QRectF(0, 0, self._image_w, self._image_h))
        self.reset_view_fit()

    def updatePixmap(self, pix: QPixmap):
        if self.scene() is None or self._pixmap_item is None:
            self.setPixmapFirstTime(pix)
            return
        self._pixmap_item.setPixmap(pix)
        self._image_w = pix.width()
        self._image_h = pix.height()
        self.scene().setSceneRect(QRectF(0, 0, self._image_w, self._image_h))

    def wheelEvent(self, event):
        zoom_in = 1.25
        zoom_out = 1 / zoom_in
        if event.angleDelta().y() > 0:
            self.scale(zoom_in, zoom_in)
        else:
            self.scale(zoom_out, zoom_out)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.LeftButton and self.capture_clicks:
            p = self.mapToScene(event.position().toPoint())
            x = int(round(p.x()))
            y = int(round(p.y()))
            if 0 <= x < self._image_w and 0 <= y < self._image_h:
                self.pointClicked.emit(x, y)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            now = event.position().toPoint()
            delta = now - self._pan_start
            self._pan_start = now
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        p = self.mapToScene(event.position().toPoint())
        x = int(round(p.x()))
        y = int(round(p.y()))
        if 0 <= x < self._image_w and 0 <= y < self._image_h:
            self.mouseMovedImg.emit(x, y)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton and self._panning:
            self._panning = False
            self._pan_start = None
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sunflower Plot Counter (PySide6)")

        self.tif_path: Optional[Path] = None
        self.out_root: Optional[Path] = None
        self.out_dir: Optional[Path] = None
        self.plots_dir: Optional[Path] = None
        self.rows_csv: Optional[Path] = None
        self.plots_csv: Optional[Path] = None
        self.annotated_path: Optional[Path] = None

        self.scale: float = 1.0
        self.px_size: float = 1.0
        self.base_overview_bgr: Optional[np.ndarray] = None
        self.annotated_bgr: Optional[np.ndarray] = None

        self.points: List[Tuple[int, int]] = []
        self.mouse_pos: Optional[Tuple[int, int]] = None
        self.preview: Optional[PreviewResult] = None

        self.thread: Optional[QThread] = None
        self.worker: Optional[PreviewWorker] = None

        self.left_mode: str = "overview"

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        self.statusBar().showMessage("Open a GeoTIFF to start.")

    def _build_shortcuts(self):
        QShortcut(QKeySequence("A"), self, activated=self._on_key_accept)
        QShortcut(QKeySequence("D"), self, activated=self._on_key_discard)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._on_key_escape)

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")

        open_act = QAction("Open GeoTIFF...", self)
        open_act.triggered.connect(self.open_tif)
        m.addAction(open_act)

        out_act = QAction("Set Output Folder...", self)
        out_act.triggered.connect(self.choose_output_root)
        m.addAction(out_act)

        m.addSeparator()

        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)
        m.addAction(quit_act)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        split = QSplitter(Qt.Horizontal)
        layout.addWidget(split)

        # Left
        left_widget = QWidget()
        left_box = QVBoxLayout(left_widget)
        left_box.setContentsMargins(0, 0, 0, 0)

        self.view = ZoomPanView()
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.pointClicked.connect(self.on_overview_click)
        self.view.mouseMovedImg.connect(self.on_overview_mouse_move)
        left_box.addWidget(self.view)

        left_btn_row = QHBoxLayout()
        self.btn_reset_view = QPushButton("Reset View")
        self.btn_show_preview_left = QPushButton("Show Preview (Left)")
        self.btn_back_overview = QPushButton("Back to Overview")
        self.btn_back_overview.setEnabled(False)
        self.btn_show_preview_left.setEnabled(False)

        left_btn_row.addWidget(self.btn_reset_view)
        left_btn_row.addWidget(self.btn_show_preview_left)
        left_btn_row.addWidget(self.btn_back_overview)
        left_btn_row.addStretch(1)
        left_box.addLayout(left_btn_row)

        self.btn_reset_view.clicked.connect(self.view.reset_view_fit)
        self.btn_show_preview_left.clicked.connect(self.show_preview_on_left)
        self.btn_back_overview.clicked.connect(self.show_overview_on_left)

        self.lbl_hint = QLabel("Clicks: 0/0 | Zoom: wheel | Pan: right-drag")
        left_box.addWidget(self.lbl_hint)

        # Right
        right_widget = QWidget()
        right_box = QVBoxLayout(right_widget)
        right_box.setContentsMargins(8, 8, 8, 8)

        split.addWidget(left_widget)
        split.addWidget(right_widget)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 2)
        split.setSizes([1200, 500])

        # Input/Output
        g_file = QGroupBox("Input / Output")
        f_file = QFormLayout(g_file)

        self.txt_tif = QLineEdit()
        self.txt_tif.setReadOnly(True)
        btn_open = QPushButton("Open GeoTIFF")
        btn_open.clicked.connect(self.open_tif)

        roww = QWidget()
        rowl = QHBoxLayout(roww)
        rowl.setContentsMargins(0, 0, 0, 0)
        rowl.addWidget(self.txt_tif, 1)
        rowl.addWidget(btn_open)
        f_file.addRow("GeoTIFF:", roww)

        self.txt_out = QLineEdit()
        self.txt_out.setReadOnly(True)
        btn_out = QPushButton("Set output folder")
        btn_out.clicked.connect(self.choose_output_root)

        roww2 = QWidget()
        rowl2 = QHBoxLayout(roww2)
        rowl2.setContentsMargins(0, 0, 0, 0)
        rowl2.addWidget(self.txt_out, 1)
        rowl2.addWidget(btn_out)
        f_file.addRow("Output root:", roww2)

        self.chk_subfolder = QCheckBox("Make subfolder per TIFF")
        self.chk_subfolder.setChecked(True)
        f_file.addRow("", self.chk_subfolder)

        # Overviews options
        self.lbl_ovr_status = QLabel("Overviews: (unknown)")
        f_file.addRow("Status:", self.lbl_ovr_status)

        self.chk_ensure_overviews = QCheckBox("Ensure overviews (pyramids) on open")
        self.chk_ensure_overviews.setChecked(False)
        f_file.addRow("", self.chk_ensure_overviews)

        self.chk_overviews_copy = QCheckBox("Build overviews on a COPY in output folder (recommended)")
        self.chk_overviews_copy.setChecked(True)
        f_file.addRow("", self.chk_overviews_copy)

        self.btn_build_overviews = QPushButton("Build overviews now…")
        self.btn_build_overviews.clicked.connect(self.build_overviews_now)
        self.btn_build_overviews.setEnabled(False)
        f_file.addRow("", self.btn_build_overviews)

        right_box.addWidget(g_file)

        # Parameters
        g_params = QGroupBox("Parameters")
        f_params = QFormLayout(g_params)

        self.spin_rows_per_plot = QSpinBox()
        self.spin_rows_per_plot.setRange(1, 24)
        self.spin_rows_per_plot.setValue(DEFAULT_ROWS_PER_PLOT)
        self.spin_rows_per_plot.setToolTip("Number of planted rows that make up a plot.")
        self.spin_rows_per_plot.valueChanged.connect(self._update_click_hint)
        f_params.addRow("Rows per plot:", self.spin_rows_per_plot)

        self.spin_row_spacing_in = QDoubleSpinBox()
        self.spin_row_spacing_in.setRange(5.0, 80.0)
        self.spin_row_spacing_in.setSingleStep(0.5)
        self.spin_row_spacing_in.setValue(DEFAULT_ROW_SPACING_IN)
        f_params.addRow("Row spacing (in):", self.spin_row_spacing_in)

        self.spin_row_width = QDoubleSpinBox()
        self.spin_row_width.setRange(0.3, 10.0)
        self.spin_row_width.setSingleStep(0.1)
        self.spin_row_width.setValue(DEFAULT_ROW_AOI_WIDTH_FT)
        f_params.addRow("Row AOI width (ft):", self.spin_row_width)

        self.chk_live = QCheckBox("Show live length")
        self.chk_live.setChecked(DEFAULT_SHOW_LIVE_LENGTH)
        f_params.addRow("", self.chk_live)

        self.spin_fixed_len = QDoubleSpinBox()
        self.spin_fixed_len.setRange(0.0, 200.0)
        self.spin_fixed_len.setSingleStep(1.0)
        self.spin_fixed_len.setValue(DEFAULT_FIXED_ROW_LENGTH_FT)
        self.spin_fixed_len.setToolTip("0 = free end-point clicking. >0 = fixed length mode (start + direction).")
        f_params.addRow("Fixed row length (ft):", self.spin_fixed_len)

        self.spin_double_factor = QDoubleSpinBox()
        self.spin_double_factor.setRange(1.0, 4.0)
        self.spin_double_factor.setSingleStep(0.05)
        self.spin_double_factor.setValue(DEFAULT_DOUBLE_FACTOR)
        f_params.addRow("Cluster factor:", self.spin_double_factor)

        self.spin_min_area = QSpinBox()
        self.spin_min_area.setRange(1, 2000)
        self.spin_min_area.setValue(DEFAULT_MIN_AREA_PX)
        f_params.addRow("Min area (px):", self.spin_min_area)

        self.spin_close = QSpinBox()
        self.spin_close.setRange(0, 30)
        self.spin_close.setValue(DEFAULT_CLOSING_RADIUS_PX)
        f_params.addRow("Closing radius (px):", self.spin_close)

        self.spin_circ = QDoubleSpinBox()
        self.spin_circ.setRange(0.0, 1.0)
        self.spin_circ.setSingleStep(0.01)
        self.spin_circ.setValue(DEFAULT_CIRCULARITY_MIN)
        f_params.addRow("Min circularity:", self.spin_circ)

        right_box.addWidget(g_params)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_undo = QPushButton("Undo")
        self.btn_reset = QPushButton("Reset")
        self.btn_preview = QPushButton("Compute Preview")
        btn_row.addWidget(self.btn_undo)
        btn_row.addWidget(self.btn_reset)
        btn_row.addWidget(self.btn_preview)
        right_box.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        self.btn_accept = QPushButton("Accept / Save")
        self.btn_discard = QPushButton("Discard")
        btn_row2.addWidget(self.btn_accept)
        btn_row2.addWidget(self.btn_discard)
        right_box.addLayout(btn_row2)

        self.btn_undo.clicked.connect(self.undo_point)
        self.btn_reset.clicked.connect(self.reset_points)
        self.btn_preview.clicked.connect(self.compute_preview)
        self.btn_accept.clicked.connect(self.accept_plot)
        self.btn_discard.clicked.connect(self.discard_plot)

        self.lbl_stats = QLabel("")
        self.lbl_stats.setWordWrap(True)
        self.lbl_stats.setStyleSheet("background:#111; color:#ddd; border:1px solid #444; padding:6px;")
        self.lbl_stats.setMinimumHeight(300)
        right_box.addWidget(self.lbl_stats, 2)

        right_box.addStretch(1)

        self._set_buttons_enabled(False)
        self._update_click_hint()

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_undo.setEnabled(enabled)
        self.btn_reset.setEnabled(enabled)
        self.btn_preview.setEnabled(enabled)
        self.btn_accept.setEnabled(False)
        self.btn_discard.setEnabled(False)

    def _update_click_hint(self):
        need = 2 * int(self.spin_rows_per_plot.value())
        self.lbl_hint.setText(f"Clicks: {len(self.points)}/{need} | Zoom: wheel | Pan: right-drag")

    # ---------- keyboard ----------
    def _on_key_accept(self):
        if self.preview is not None and self.btn_accept.isEnabled():
            self.accept_plot()

    def _on_key_discard(self):
        if self.preview is not None and self.btn_discard.isEnabled():
            self.discard_plot()

    def _on_key_escape(self):
        if self.preview is not None:
            self.discard_plot()

    # ---------- output ----------
    def choose_output_root(self):
        d = QFileDialog.getExistingDirectory(self, "Select output root folder")
        if not d:
            return
        self.out_root = Path(d)
        self.txt_out.setText(str(self.out_root))
        if self.tif_path:
            self._init_outputs()
            self._load_overview()
            self.reset_points()

    def _init_outputs(self):
        assert self.tif_path is not None
        assert self.out_root is not None
        if self.chk_subfolder.isChecked():
            out_dir = self.out_root / f"{self.tif_path.stem}_plot_counts_outputs"
        else:
            out_dir = self.out_root / "plot_counts_outputs"
        self.out_dir = out_dir
        self.plots_dir, self.rows_csv, self.plots_csv, self.annotated_path = ensure_outputs(out_dir)

    # ---------- overviews integration ----------
    def _update_overview_status_label(self):
        if not self.tif_path:
            self.lbl_ovr_status.setText("Overviews: (no file)")
            return
        ok = has_overviews(self.tif_path, band=1)
        self.lbl_ovr_status.setText(f"Overviews: {'Yes' if ok else 'No'}")

    def _ensure_overviews_if_requested(self):
        if not self.tif_path:
            return
        if not self.chk_ensure_overviews.isChecked():
            self._update_overview_status_label()
            return
        self._build_overviews_flow(interactive_on_fail=True)

    def build_overviews_now(self):
        if not self.tif_path:
            return
        self._build_overviews_flow(interactive_on_fail=True)
        # reload overview for better display
        self._load_overview()
        self.reset_points()

    def _build_overviews_flow(self, interactive_on_fail: bool):
        """
        Build overviews either in-place or on a COPY in output folder.
        If COPY is selected, the session switches to the copied TIFF.
        """
        try:
            target_path = self.tif_path

            # If requested, copy to output folder
            if self.chk_overviews_copy.isChecked():
                if self.out_root is None:
                    self.out_root = self.tif_path.parent
                    self.txt_out.setText(str(self.out_root))
                if self.out_dir is None:
                    self._init_outputs()
                assert self.out_dir is not None

                copied = self.out_dir / f"{self.tif_path.stem}_with_overviews{self.tif_path.suffix}"
                if not copied.exists():
                    self.statusBar().showMessage("Copying GeoTIFF to output folder (for overviews)...")
                    QApplication.setOverrideCursor(Qt.WaitCursor)
                    try:
                        shutil.copy2(self.tif_path, copied)
                    finally:
                        QApplication.restoreOverrideCursor()
                target_path = copied

            # If missing, build them
            if not has_overviews(target_path, band=1):
                self.statusBar().showMessage("Building overviews (pyramids)... this may take a while")
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    build_overviews_inplace(target_path, levels=DEFAULT_OVERVIEW_LEVELS, resampling=Resampling.average)
                finally:
                    QApplication.restoreOverrideCursor()

            # Switch session TIFF if we used the copy
            self.tif_path = target_path
            self.txt_tif.setText(str(self.tif_path))
            self._update_overview_status_label()

            self.statusBar().showMessage("Overviews ready.")

        except Exception as e:
            self._update_overview_status_label()
            if interactive_on_fail:
                QMessageBox.warning(
                    self,
                    "Overview build failed",
                    f"Could not build overviews automatically.\n\nReason:\n{e}\n\n"
                    "The tool will continue without overviews, but navigation may be slower or pixelated.\n"
                    "Tip: If you lack write permissions, enable 'Build overviews on a COPY'."
                )

    # ---------- file ----------
    def open_tif(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open GeoTIFF", "", "GeoTIFF (*.tif *.tiff)")
        if not fn:
            return
        self.tif_path = Path(fn)
        self.txt_tif.setText(str(self.tif_path))

        if self.out_root is None:
            self.out_root = self.tif_path.parent
            self.txt_out.setText(str(self.out_root))

        self._init_outputs()

        # enable manual build button now that we have a TIFF
        self.btn_build_overviews.setEnabled(True)

        # Optional: build/ensure overviews (possibly on a copy)
        self._ensure_overviews_if_requested()

        self._load_overview()
        self.reset_points()
        self.statusBar().showMessage(f"Loaded overview. Output: {self.out_dir}")

    # ---------- overview load/render ----------
    def _load_overview(self):
        if not self.tif_path or not self.out_dir:
            return

        with rasterio.open(str(self.tif_path)) as ds:
            px_size_x = abs(ds.transform.a)
            px_size_y = abs(ds.transform.e)
            self.px_size = (px_size_x + px_size_y) / 2.0

            self.scale = min(DEFAULT_MAX_OVERVIEW_DIM / ds.width, DEFAULT_MAX_OVERVIEW_DIM / ds.height, 1.0)
            ovr_w = int(ds.width * self.scale)
            ovr_h = int(ds.height * self.scale)

            r_i, g_i, b_i = DEFAULT_USE_BANDS_RGB
            r = ds.read(r_i, out_shape=(ovr_h, ovr_w), resampling=DEFAULT_OVERVIEW_RESAMPLING).astype(np.float32)
            g = ds.read(g_i, out_shape=(ovr_h, ovr_w), resampling=DEFAULT_OVERVIEW_RESAMPLING).astype(np.float32)
            b = ds.read(b_i, out_shape=(ovr_h, ovr_w), resampling=DEFAULT_OVERVIEW_RESAMPLING).astype(np.float32)
            self.base_overview_bgr = percentile_stretch_to_uint8(np.dstack([r, g, b]))

        if self.annotated_path and self.annotated_path.exists():
            ann = cv2.imread(str(self.annotated_path), cv2.IMREAD_COLOR)
            if ann is not None and ann.shape[:2] == self.base_overview_bgr.shape[:2]:
                self.annotated_bgr = ann
            else:
                self.annotated_bgr = self.base_overview_bgr.copy()
        else:
            self.annotated_bgr = self.base_overview_bgr.copy()

        self._update_overview_status_label()

        self.left_mode = "overview"
        self.view.set_capture_clicks(True)
        self.btn_back_overview.setEnabled(False)
        self.btn_show_preview_left.setEnabled(False)

        pix = QPixmap.fromImage(bgr_to_qimage(self.annotated_bgr))
        self.view.setPixmapFirstTime(pix)
        self._render_overview()
        self._set_buttons_enabled(True)

    def _render_overview(self):
        if self.annotated_bgr is None or self.left_mode != "overview":
            return

        img = self.annotated_bgr.copy()
        n_rows = int(self.spin_rows_per_plot.value())

        for i, (x, y) in enumerate(self.points):
            cv2.circle(img, (x, y), 3, (0, 255, 255), -1)
            cv2.putText(img, str(i + 1), (x + 6, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)

        for rr in range(n_rows):
            i0, i1 = 2 * rr, 2 * rr + 1
            if len(self.points) > i1:
                cv2.line(img, self.points[i0], self.points[i1], (0, 255, 255), 1)

        if (
            self.chk_live.isChecked()
            and self.mouse_pos is not None
            and (len(self.points) % 2 == 1)
            and (len(self.points) < 2 * n_rows)
        ):
            start = self.points[-1]
            end = self.mouse_pos
            cv2.line(img, start, end, (255, 255, 255), 1)

            dx = end[0] - start[0]
            dy = end[1] - start[1]
            dist_ovr_px = math.sqrt(dx * dx + dy * dy)
            dist_full_px = dist_ovr_px / self.scale
            dist_m = dist_full_px * self.px_size
            dist_ft = dist_m / FT_TO_M
            cv2.putText(img, f"{dist_ft:.1f} ft", (end[0] + 10, end[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

        pix = QPixmap.fromImage(bgr_to_qimage(img))
        self.view.updatePixmap(pix)
        self._update_click_hint()

    # ---------- interaction ----------
    def on_overview_mouse_move(self, x: int, y: int):
        self.mouse_pos = (x, y)
        if self.left_mode == "overview":
            self._render_overview()

    def on_overview_click(self, x: int, y: int):
        if self.left_mode != "overview" or not self.tif_path or self.thread is not None:
            return

        n_rows = int(self.spin_rows_per_plot.value())
        need = 2 * n_rows
        if len(self.points) >= need:
            return

        self.points.append((x, y))

        fixed_len = float(self.spin_fixed_len.value())
        if fixed_len > 0 and len(self.points) % 2 == 0:
            start = np.array(self.points[-2], dtype=np.float32)
            direction = np.array(self.points[-1], dtype=np.float32)
            v = direction - start
            n = float(np.linalg.norm(v))
            if n > 1e-6:
                u = v / n
                fixed_pixels_ovr = (fixed_len * FT_TO_M / self.px_size) * self.scale
                end = start + u * fixed_pixels_ovr
                self.points[-1] = (int(round(end[0])), int(round(end[1])))

        self.preview = None
        self.btn_show_preview_left.setEnabled(False)
        self.btn_accept.setEnabled(False)
        self.btn_discard.setEnabled(False)
        self.lbl_stats.setText("")
        self._render_overview()

        if len(self.points) == need:
            self.compute_preview(auto=True)

    def undo_point(self):
        if self.thread is not None:
            return
        if self.points:
            self.points.pop()
            self.preview = None
            self.btn_show_preview_left.setEnabled(False)
            self.btn_accept.setEnabled(False)
            self.btn_discard.setEnabled(False)
            self.lbl_stats.setText("")
            self._render_overview()

    def reset_points(self):
        if self.thread is not None:
            return
        self.points = []
        self.preview = None
        self.btn_show_preview_left.setEnabled(False)
        self.btn_accept.setEnabled(False)
        self.btn_discard.setEnabled(False)
        self.lbl_stats.setText("")
        if self.left_mode == "overview":
            self._render_overview()
        self._update_click_hint()

    # ---------- preview ----------
    def compute_preview(self, auto: bool = False):
        if not self.tif_path or not self.out_dir:
            if not auto:
                QMessageBox.warning(self, "Missing input", "Open a GeoTIFF first.")
            return

        n_rows = int(self.spin_rows_per_plot.value())
        need = 2 * n_rows
        if len(self.points) != need:
            if not auto:
                QMessageBox.information(self, "Need more points", f"Collect {need} points first.")
            return

        if self.thread is not None:
            return

        self.statusBar().showMessage("Computing preview...")
        self.lbl_stats.setText("Computing preview...")
        self._set_busy(True)

        self.thread = QThread()
        self.worker = PreviewWorker(
            tif_path=str(self.tif_path),
            points_ovr=self.points.copy(),
            n_rows=n_rows,
            scale=self.scale,
            px_size=self.px_size,
            row_aoi_width_ft=float(self.spin_row_width.value()),
            bands_rgb=DEFAULT_USE_BANDS_RGB,
            min_area_px=int(self.spin_min_area.value()),
            closing_radius_px=int(self.spin_close.value()),
            circ_min=float(self.spin_circ.value()),
            baseline_stat=DEFAULT_BASELINE_STAT,
            double_factor=float(self.spin_double_factor.value()),
            max_cluster_mult=DEFAULT_MAX_CLUSTER_MULTIPLIER,
            use_adjusted=DEFAULT_USE_ADJUSTED_COUNTS,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_preview_done)
        self.worker.failed.connect(self._on_preview_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup_thread)
        self.thread.start()

    def _set_busy(self, busy: bool):
        self.btn_undo.setEnabled(not busy)
        self.btn_reset.setEnabled(not busy)
        self.btn_preview.setEnabled(not busy)
        self.btn_accept.setEnabled(False if busy else self.preview is not None)
        self.btn_discard.setEnabled(False if busy else self.preview is not None)

    def _cleanup_thread(self):
        self.thread = None
        self.worker = None
        self._set_busy(False)

    def _on_preview_failed(self, msg: str):
        self.statusBar().showMessage("Preview failed.")
        self.lbl_stats.setText("Preview failed.\n" + msg)
        QMessageBox.critical(self, "Preview failed", msg)

    def _compute_lengths_and_rates(
        self,
        points: List[Tuple[int, int]],
        n_rows: int,
        row_adj: List[int],
        plot_sum_adj: int,
        plot_sum_raw: int
    ):
        row_spacing_in = float(self.spin_row_spacing_in.value())
        row_spacing_ft = row_spacing_in / 12.0

        row_lengths_ft: List[float] = []
        for rr in range(n_rows):
            p0 = np.array(points[2 * rr], dtype=np.float32)
            p1 = np.array(points[2 * rr + 1], dtype=np.float32)
            dist_ovr_px = float(np.linalg.norm(p1 - p0))
            dist_full_px = dist_ovr_px / self.scale
            dist_m = dist_full_px * self.px_size
            dist_ft = dist_m / FT_TO_M
            row_lengths_ft.append(dist_ft)

        row_lengths_ft_round = [round(x, 2) for x in row_lengths_ft]

        plants_per_ft_adj: List[float] = []
        for rr in range(n_rows):
            L = row_lengths_ft[rr]
            plants_per_ft_adj.append(round(float(row_adj[rr]) / L, 3) if L > 1e-6 else 0.0)

        plot_area_ft2 = float(np.sum(np.array(row_lengths_ft, dtype=np.float64) * row_spacing_ft))
        if plot_area_ft2 > 1e-9:
            plot_pacre_adj = float(plot_sum_adj) * ACRE_FT2 / plot_area_ft2
            plot_pacre_raw = float(plot_sum_raw) * ACRE_FT2 / plot_area_ft2
        else:
            plot_pacre_adj = 0.0
            plot_pacre_raw = 0.0

        return row_lengths_ft_round, plants_per_ft_adj, plot_pacre_adj, plot_pacre_raw, plot_area_ft2

    def _on_preview_done(self, res: PreviewResult):
        self.preview = res
        self.btn_accept.setEnabled(True)
        self.btn_discard.setEnabled(True)
        self.btn_show_preview_left.setEnabled(True)

        n_rows = int(self.spin_rows_per_plot.value())

        row_lengths_ft, plants_per_ft_adj, plot_pacre_adj, plot_pacre_raw, plot_area_ft2 = \
            self._compute_lengths_and_rates(
                points=self.points,
                n_rows=n_rows,
                row_adj=res.row_adj,
                plot_sum_adj=res.plot_sum_adj,
                plot_sum_raw=res.plot_sum_raw
            )

        self.statusBar().showMessage("Preview ready. Press 'a' accept, 'd' discard. (Optional: Show Preview (Left))")

        self.lbl_stats.setText(
            f"Rows per plot: {n_rows}\n"
            f"Row spacing (in): {float(self.spin_row_spacing_in.value()):.1f}\n"
            f"Row lengths (ft): {row_lengths_ft}\n"
            f"Row plants/ft (adj): {plants_per_ft_adj}\n"
            f"Plot area (ft^2): {plot_area_ft2:.2f}\n"
            f"Plot plants/acre (adj): {plot_pacre_adj:.0f} | (raw): {plot_pacre_raw:.0f}\n\n"
            f"Row adjusted: {res.row_adj}\n"
            f"Row raw:      {res.row_raw}\n"
            f"Clusters:     {res.row_clusters}\n"
            f"Plot SUM adjusted: {res.plot_sum_adj}   (raw: {res.plot_sum_raw})\n\n"
            f"Keyboard: 'a' accept/save | 'd' discard | ESC discard preview\n"
            f"Optional: click 'Show Preview (Left)' to inspect detections."
        )

    # ---------- left switching ----------
    def show_overview_on_left(self):
        if self.annotated_bgr is None:
            return
        self.left_mode = "overview"
        self.view.set_capture_clicks(True)
        self.btn_back_overview.setEnabled(False)

        st = self.view.get_view_state()
        pix = QPixmap.fromImage(bgr_to_qimage(self.annotated_bgr))
        self.view.setPixmapFirstTime(pix)
        self.view.set_view_state(st)

        self._render_overview()

    def show_preview_on_left(self):
        if self.preview is None:
            return
        self.left_mode = "preview"
        self.view.set_capture_clicks(False)
        self.btn_back_overview.setEnabled(True)

        pix = QPixmap.fromImage(bgr_to_qimage(self.preview.vis_bgr))
        self.view.setPixmapFirstTime(pix)
        self.statusBar().showMessage("Preview on left. Zoom/pan to inspect. Press 'a' accept, 'd' discard, ESC discard.")

    # ---------- accept/discard ----------
    def discard_plot(self):
        self.preview = None
        self.points = []
        self.btn_show_preview_left.setEnabled(False)
        self.btn_accept.setEnabled(False)
        self.btn_discard.setEnabled(False)
        self.lbl_stats.setText("")
        self.statusBar().showMessage("Discarded. Continue with next plot.")
        if self.left_mode == "overview":
            self._render_overview()
        self._update_click_hint()

    def accept_plot(self):
        if not self.preview or not self.plots_dir or not self.rows_csv or not self.plots_csv or not self.annotated_path:
            return
        if self.annotated_bgr is None:
            return

        plot_id = next_plot_id_from_plots_csv(self.plots_csv)
        n_rows = int(self.spin_rows_per_plot.value())
        row_spacing_in = float(self.spin_row_spacing_in.value())

        annot_name = f"plot_{plot_id:04d}_annot.png"
        raw_name = f"plot_{plot_id:04d}_raw.png"
        annot_path_plot = self.plots_dir / annot_name
        raw_path_plot = self.plots_dir / raw_name
        cv2.imwrite(str(raw_path_plot), self.preview.crop_bgr)
        cv2.imwrite(str(annot_path_plot), self.preview.vis_bgr)

        row_lengths_ft, plants_per_ft_adj, plot_pacre_adj, plot_pacre_raw, plot_area_ft2 = \
            self._compute_lengths_and_rates(
                points=self.points,
                n_rows=n_rows,
                row_adj=self.preview.row_adj,
                plot_sum_adj=self.preview.plot_sum_adj,
                plot_sum_raw=self.preview.plot_sum_raw
            )

        all_pts = self.preview.all_pts_full
        hull_ovr = convex_hull_poly(all_pts * self.scale)
        center_full = np.mean(all_pts, axis=0)
        center_ovr = center_full * self.scale

        for idx, poly_full in enumerate(self.preview.row_polys_full, start=1):
            poly_ovr = poly_full * self.scale
            draw_poly(self.annotated_bgr, poly_ovr, AOI_COLOR, 1)
            tx, ty = int(np.min(poly_ovr[:, 0])), int(np.min(poly_ovr[:, 1]))
            cv2.putText(self.annotated_bgr, f"P{plot_id}R{idx}:{self.preview.row_adj[idx-1]}",
                        (tx + 2, ty + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, NORMAL_COLOR, 2, cv2.LINE_AA)

        cv2.polylines(self.annotated_bgr, [hull_ovr], True, (255, 255, 255), 2)
        cv2.putText(self.annotated_bgr, f"P{plot_id} adj={self.preview.plot_sum_adj}",
                    (int(center_ovr[0]) - 60, int(center_ovr[1])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        cv2.imwrite(str(self.annotated_path), self.annotated_bgr)

        with open(self.rows_csv, "a", newline="") as f:
            w = csv.writer(f)
            for rr in range(n_rows):
                w.writerow([
                    plot_id, rr + 1,
                    row_spacing_in,
                    row_lengths_ft[rr],
                    self.preview.row_adj[rr],
                    self.preview.row_raw[rr],
                    self.preview.row_clusters[rr],
                    plants_per_ft_adj[rr]
                ])

        with open(self.plots_csv, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                plot_id,
                n_rows,
                row_spacing_in,
                round(plot_area_ft2, 2),
                self.preview.plot_sum_adj,
                self.preview.plot_sum_raw,
                round(plot_pacre_adj, 2),
                round(plot_pacre_raw, 2),
                annot_name,
                raw_name
            ])

        current_zoom = self.view.transform()

        self.preview = None
        self.points = []
        self.btn_show_preview_left.setEnabled(False)
        self.btn_accept.setEnabled(False)
        self.btn_discard.setEnabled(False)
        self.lbl_stats.setText("")

        if self.left_mode != "overview":
            self.left_mode = "overview"
            self.view.set_capture_clicks(True)
            self.btn_back_overview.setEnabled(False)
            pix = QPixmap.fromImage(bgr_to_qimage(self.annotated_bgr))
            self.view.setPixmapFirstTime(pix)
            self.view.setTransform(current_zoom)
        else:
            st = self.view.get_view_state()
            pix = QPixmap.fromImage(bgr_to_qimage(self.annotated_bgr))
            self.view.updatePixmap(pix)
            self.view.set_view_state(st)

        self._render_overview()
        self.view.centerOn(QPointF(float(center_ovr[0]), float(center_ovr[1])))

        self.statusBar().showMessage(
            f"Saved Plot {plot_id} | plants/ac(adj)={plot_pacre_adj:.0f} | updated plots.csv/rows.csv"
        )
        self._update_click_hint()


def main():
    app = QApplication([])
    w = MainWindow()
    w.resize(1600, 900)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()