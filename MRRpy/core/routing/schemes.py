# -*- coding: utf-8 -*-
"""
schemes.py
==========
Registry of channel-routing schemes for the explicit grid solver.

Each ``RoutingScheme`` is a small descriptor that names a scheme and declares
the *behavioural traits* the time loop (``router.run_time_loop``) needs to
branch on, so those decisions are data-driven from one place rather than
scattered ``scheme == '...'`` / ``_mc`` string checks:

  * ``rate_based`` — the scheme's state is per-cell **outflow rate**, not stored
    volume (Muskingum–Cunge).  Such schemes have no volume ledger and skip the
    volume-conservative flux limiter; they get their own outflow update and
    diagnostic instead.
  * ``needs_water_surface_slope`` — the friction slope is the **water-surface**
    slope (bed + depth gradient), i.e. the diffusion-wave discharge kernel, as
    opposed to the plain bed slope used by the kinematic kernel.

The discharge *numerics* for the three built-ins live inline in ``router.py``
(they differ enough — Muskingum–Cunge is a multi-substep update — that a single
generic call would obscure the solver).  Adding a genuinely new scheme means
registering its descriptor here **and** wiring its discharge step in the time
loop; adding one that reuses an existing kernel with different traits is just a
new ``RoutingScheme`` entry.

The scheme *names* must match the ``ROUTING_SCHEME`` entries in
``MRRpy.config._ENUM_CHOICES`` (that registry drives config validation and
the integer option codes; this one drives runtime dispatch).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingScheme:
    """Descriptor for one routing scheme (see module docstring)."""
    name: str
    label: str                              # printed at run start (may use {theta})
    rate_based: bool = False                # Muskingum–Cunge: state is outflow rate
    needs_water_surface_slope: bool = False  # diffusion wave: water-surface slope
    momentum_state: bool = False            # local-inertial: carries per-face discharge (∂Q/∂t)

    def describe(self, theta=1.0):
        """The run-start log line, with the diffusion weight substituted in."""
        return self.label.format(theta=theta)


#: name → RoutingScheme
ROUTING_SCHEMES = {}


def register_scheme(scheme):
    """Register *scheme* under its name (also usable as a decorator)."""
    ROUTING_SCHEMES[scheme.name] = scheme
    return scheme


register_scheme(RoutingScheme(
    name="kinematic",
    label="KINEMATIC wave (bed slope)",
))
register_scheme(RoutingScheme(
    name="diffusive",
    label="DIFFUSIVE wave (water-surface slope, θ={theta:g})",
    needs_water_surface_slope=True,
))
register_scheme(RoutingScheme(
    name="muskingum",
    label="MUSKINGUM–CUNGE (variable-parameter; physical diffusion "
          "D=Q/(2BS₀), grid-independent)",
    rate_based=True,
))
register_scheme(RoutingScheme(
    name="dynamic",
    label="DYNAMIC wave (local-inertial / LISFLOOD-FP; ∂Q/∂t + surface "
          "slope + semi-implicit friction — shock-preserving)",
    needs_water_surface_slope=True,   # uses WSE gradient + h-over-higher-bed geometry
    momentum_state=True,              # persists per-face Q across steps
))


def get_scheme(name):
    """Resolve a scheme name to its descriptor, defaulting to kinematic."""
    return ROUTING_SCHEMES.get(str(name).lower(), ROUTING_SCHEMES["kinematic"])
