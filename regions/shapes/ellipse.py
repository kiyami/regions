# Licensed under a 3-clause BSD style license - see LICENSE.rst
import math

import numpy as np
from astropy import units as u
from astropy.coordinates import Angle
from astropy.wcs.utils import pixel_to_skycoord

from ..core import PixCoord, PixelRegion, SkyRegion, RegionMask, BoundingBox
from .._geometry import elliptical_overlap_grid
from .._utils.wcs_helpers import skycoord_to_pixel_scale_angle
from ..core.attributes import (ScalarPix, ScalarLength, QuantityLength,
                               ScalarSky, RegionMeta, RegionVisual)


__all__ = ['EllipsePixelRegion', 'EllipseSkyRegion']


class EllipsePixelRegion(PixelRegion):
    """
    An ellipse in pixel coordinates.

    Parameters
    ----------
    center : `~regions.PixCoord`
        The position of the center of the ellipse.
    width : `float`
        The width of the ellipse (before rotation) in pixels
    height : `float`
        The height of the ellipse (before rotation) in pixels
    angle : `~astropy.units.Quantity`, optional
        The rotation angle of the ellipse, measured anti-clockwise. If set to
        zero (the default), the width axis is lined up with the x axis.
    meta : `~regions.RegionMeta` object, optional
        A dictionary which stores the meta attributes of this region.
    visual : `~regions.RegionVisual` object, optional
        A dictionary which stores the visual meta attributes of this region.

    Examples
    --------

    .. plot::
        :include-source:

        import numpy as np
        from astropy.modeling.models import Ellipse2D
        from astropy.coordinates import Angle
        from regions import PixCoord, EllipsePixelRegion
        import matplotlib.pyplot as plt
        x0, y0 = 15, 10
        a, b = 8, 5
        theta = Angle(30, 'deg')
        e = Ellipse2D(amplitude=100., x_0=x0, y_0=y0, a=a, b=b, theta=theta.radian)
        y, x = np.mgrid[0:20, 0:30]
        fig, ax = plt.subplots(1, 1)
        ax.imshow(e(x, y), origin='lower', interpolation='none', cmap='Greys_r')

        center = PixCoord(x=x0, y=y0)
        reg = EllipsePixelRegion(center=center, width=2*a, height=2*b, angle=theta)
        patch = reg.as_artist(facecolor='none', edgecolor='red', lw=2)
        ax.add_patch(patch)

    """
    _params = ('center', 'width', 'height', 'angle')
    center = ScalarPix('center')
    width = ScalarLength('width')
    height = ScalarLength('height')
    angle = QuantityLength('angle')

    def __init__(self, center, width, height, angle=0. * u.deg, meta=None,
                 visual=None):
        self.center = center
        self.width = width
        self.height = height
        self.angle = angle
        self.meta = meta or RegionMeta()
        self.visual = visual or RegionVisual()

    @property
    def area(self):
        """Region area (float)"""
        return math.pi / 4 * self.width * self.height

    def contains(self, pixcoord):
        pixcoord = PixCoord._validate(pixcoord, name='pixcoord')
        cos_angle = np.cos(self.angle)
        sin_angle = np.sin(self.angle)
        dx = pixcoord.x - self.center.x
        dy = pixcoord.y - self.center.y
        in_ell = ((2 * (cos_angle * dx + sin_angle * dy) / self.width) ** 2 +
                  (2 * (sin_angle * dx - cos_angle * dy) / self.height) ** 2 <= 1.)
        if self.meta.get('include', True):
            return in_ell
        else:
            return np.logical_not(in_ell)

    def to_sky(self, wcs):
        # TODO: write a pixel_to_skycoord_scale_angle
        center = pixel_to_skycoord(self.center.x, self.center.y, wcs)
        _, scale, north_angle = skycoord_to_pixel_scale_angle(center, wcs)
        height = Angle(self.height / scale, 'deg')
        width = Angle(self.width / scale, 'deg')
        return EllipseSkyRegion(center, width, height,
                                angle=self.angle - (north_angle - 90 * u.deg),
                                meta=self.meta, visual=self.visual)

    @property
    def bounding_box(self):
        """
        The minimal bounding box (`~regions.BoundingBox`) enclosing the
        exact elliptical region.
        """

        # We use the solution described in http://stackoverflow.com/a/88020
        # which is to use the parametric equation of an ellipse and to find
        # when dx/dt or dy/dt=0.

        cos_angle = np.cos(self.angle)
        sin_angle = np.sin(self.angle)
        tan_angle = np.tan(self.angle)

        t1 = np.arctan(-self.height * tan_angle / self.width)
        t2 = t1 + np.pi * u.rad

        dx1 = 0.5 * self.width * cos_angle * np.cos(t1) - 0.5 * self.height * sin_angle * np.sin(t1)
        dx2 = 0.5 * self.width * cos_angle * np.cos(t2) - 0.5 * self.height * sin_angle * np.sin(t2)

        if dx1 > dx2:
            dx1, dx2 = dx2, dx1

        t1 = np.arctan(self.height / tan_angle / self.width)
        t2 = t1 + np.pi * u.rad

        dy1 = 0.5 * self.height * cos_angle * np.sin(t1) + 0.5 * self.width * sin_angle * np.cos(t1)
        dy2 = 0.5 * self.height * cos_angle * np.sin(t2) + 0.5 * self.width * sin_angle * np.cos(t2)

        if dy1 > dy2:
            dy1, dy2 = dy2, dy1

        xmin = self.center.x + dx1
        xmax = self.center.x + dx2
        ymin = self.center.y + dy1
        ymax = self.center.y + dy2

        return BoundingBox.from_float(xmin, xmax, ymin, ymax)

    def to_mask(self, mode='center', subpixels=5):

        # NOTE: assumes this class represents a single circle

        self._validate_mode(mode, subpixels)

        if mode == 'center':
            mode = 'subpixels'
            subpixels = 1

        # Find bounding box and mask size
        bbox = self.bounding_box
        ny, nx = bbox.shape

        # Find position of pixel edges and recenter so that ellipse is at origin
        xmin = float(bbox.ixmin) - 0.5 - self.center.x
        xmax = float(bbox.ixmax) - 0.5 - self.center.x
        ymin = float(bbox.iymin) - 0.5 - self.center.y
        ymax = float(bbox.iymax) - 0.5 - self.center.y

        if mode == 'subpixels':
            use_exact = 0
        else:
            use_exact = 1

        fraction = elliptical_overlap_grid(
            xmin, xmax, ymin, ymax, nx, ny,
            0.5 * self.width, 0.5 * self.height,
            self.angle.to(u.rad).value,
            use_exact, subpixels,
        )

        return RegionMask(fraction, bbox=bbox)

    def as_artist(self, origin=(0, 0), **kwargs):
        """
        Matplotlib patch object for this region (`matplotlib.patches.Ellipse`).

        Parameters
        ----------
        origin : array_like, optional
            The ``(x, y)`` pixel position of the origin of the displayed image.
            Default is (0, 0).
        kwargs : `dict`
            All keywords that a `~matplotlib.patches.Ellipse` object accepts

        Returns
        -------
        patch : `~matplotlib.patches.Ellipse`
            Matplotlib ellipse patch

        """
        from matplotlib.patches import Ellipse
        xy = self.center.x - origin[0], self.center.y - origin[1]
        width = self.width
        height = self.height
        # From the docstring: MPL expects "rotation in degrees (anti-clockwise)"
        angle = self.angle.to('deg').value

        mpl_params = self.mpl_properties_default('patch')
        mpl_params.update(kwargs)

        return Ellipse(xy=xy, width=width, height=height, angle=angle,
                       **mpl_params)

    def _update_from_mpl_selector(self, *args, **kwargs):
        xmin, xmax, ymin, ymax = self._mpl_selector.extents
        self.center = PixCoord(x=0.5 * (xmin + xmax),
                               y=0.5 * (ymin + ymax))
        self.width = (xmax - xmin)
        self.height = (ymax - ymin)
        self.angle = 0. * u.deg
        if self._mpl_selector_callback is not None:
            self._mpl_selector_callback(self)

    def as_mpl_selector(self, ax, active=True, sync=True, callback=None, **kwargs):
        """
        Matplotlib editable widget for this region (`matplotlib.widgets.EllipseSelector`)

        Parameters
        ----------
        ax : `~matplotlib.axes.Axes`
            The Matplotlib axes to add the selector to.
        active : bool, optional
            Whether the selector should be active by default.
        sync : bool, optional
            If `True` (the default), the region will be kept in sync with the
            selector. Otherwise, the selector will be initialized with the
            values from the region but the two will then be disconnected.
        callback : func, optional
            If specified, this function will be called every time the region is
            updated. This only has an effect if ``sync`` is `True`. If a
            callback is set, it is called for the first time once the selector
            has been created.
        kwargs
            Additional keyword arguments are passed to matplotlib.widgets.EllipseSelector`

        Returns
        -------
        selector : `matplotlib.widgets.EllipseSelector`
            The Matplotlib selector.

        Notes
        -----
        Once a selector has been created, you will need to keep a reference to
        it until you no longer need it. In addition, you can enable/disable the
        selector at any point by calling ``selector.set_active(True)`` or
        ``selector.set_active(False)``.
        """

        from matplotlib.widgets import EllipseSelector

        if hasattr(self, '_mpl_selector'):
            raise Exception("Cannot attach more than one selector to a region.")

        if self.angle.value != 0:
            raise NotImplementedError("Cannot create matplotlib selector for rotated ellipse.")

        if sync:
            sync_callback = self._update_from_mpl_selector
        else:
            def sync_callback(*args, **kwargs):
                pass

        self._mpl_selector = EllipseSelector(ax, sync_callback, interactive=True,
                                             rectprops={'edgecolor': self.visual.get('color', 'black'),
                                                        'facecolor': 'none',
                                                        'linewidth': self.visual.get('linewidth', 1),
                                                        'linestyle': self.visual.get('linestyle', 'solid')})
        self._mpl_selector.extents = (self.center.x - self.width / 2,
                                      self.center.x + self.width / 2,
                                      self.center.y - self.height / 2,
                                      self.center.y + self.height / 2)
        self._mpl_selector.set_active(active)
        self._mpl_selector_callback = callback

        if sync and self._mpl_selector_callback is not None:
            self._mpl_selector_callback(self)

        return self._mpl_selector

    def rotate(self, center, angle):
        """Make a rotated region.

        Rotates counter-clockwise for positive ``angle``.

        Parameters
        ----------
        center : `PixCoord`
            Rotation center point
        angle : `~astropy.coordinates.Angle`
            Rotation angle

        Returns
        -------
        region : `EllipsePixelRegion`
            Rotated region (an independent copy)
        """
        center = self.center.rotate(center, angle)
        angle = self.angle + angle
        return self.copy(center=center, angle=angle)


class EllipseSkyRegion(SkyRegion):
    """
    An ellipse defined using sky coordinates.

    Parameters
    ----------
    center : `~astropy.coordinates.SkyCoord`
        The position of the center of the ellipse.
    width : `~astropy.units.Quantity`
        The width of the ellipse (before rotation) as an angle
    height : `~astropy.units.Quantity`
        The height of the ellipse (before rotation) as an angle
    angle : `~astropy.units.Quantity`, optional
        The rotation angle of the ellipse, measured anti-clockwise. If set to
        zero (the default), the width axis is lined up with the longitude axis
        of the celestial coordinates.
    meta : `~regions.RegionMeta` object, optional
        A dictionary which stores the meta attributes of this region.
    visual : `~regions.RegionVisual` object, optional
        A dictionary which stores the visual meta attributes of this region.
    """
    _params = ('center', 'width', 'height', 'angle')
    center = ScalarSky('center')
    width = QuantityLength('width')
    height = QuantityLength('height')
    angle = QuantityLength('angle')

    def __init__(self, center, width, height, angle=0. * u.deg, meta=None, visual=None):
        self.center = center
        self.width = width
        self.height = height
        self.angle = angle
        self.meta = meta or RegionMeta()
        self.visual = visual or RegionVisual()

    def to_pixel(self, wcs):
        center, scale, north_angle = skycoord_to_pixel_scale_angle(self.center, wcs)
        # FIXME: The following line is needed to get a scalar PixCoord
        center = PixCoord(float(center.x), float(center.y))
        height = self.height.to('deg').value * scale
        width = self.width.to('deg').value * scale
        return EllipsePixelRegion(center, width, height,
                                  angle=self.angle + (north_angle - 90 * u.deg),
                                  meta=self.meta, visual=self.visual)
