from __future__ import annotations

import random
from dataclasses import dataclass

from rich.text import Text

PARTICLE_CHARS = ("✦", "·", "✧", "+")
PARTICLE_COLORS = ("bright_green", "green", "cyan", "bright_cyan", "yellow")


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    age: float
    ttl: float
    char: str
    color: str

    @property
    def alive(self) -> bool:
        return self.age < self.ttl

    @property
    def fade_index(self) -> int:
        if self.ttl <= 0:
            return len(PARTICLE_COLORS) - 1
        return min(len(PARTICLE_COLORS) - 1, int((self.age / self.ttl) * len(PARTICLE_COLORS)))


class ParticleSystem:
    """Bounded particle state used by the Textual particle canvas."""

    def __init__(self, max_particles: int = 96, *, seed: int | None = None) -> None:
        self.max_particles = max(0, max_particles)
        self._rng = random.Random(seed)
        self.particles: list[Particle] = []

    def spawn(
        self,
        count: int,
        *,
        width: int = 40,
        height: int = 3,
        color: str = "bright_green",
        x: float | None = None,
        y: float | None = None,
    ) -> None:
        if count <= 0 or self.max_particles <= 0:
            return
        count = min(count, self.max_particles)
        usable_width = max(1, width)
        usable_height = max(1, height)
        origin_x = usable_width / 2 if x is None else x
        origin_y = usable_height - 1 if y is None else y
        for _ in range(count):
            self.particles.append(
                Particle(
                    x=origin_x + self._rng.uniform(-1.5, 1.5),
                    y=origin_y + self._rng.uniform(-0.5, 0.5),
                    vx=self._rng.uniform(-1.8, 1.8),
                    vy=self._rng.uniform(-1.8, 0.3),
                    age=0.0,
                    ttl=self._rng.uniform(0.45, 1.0),
                    char=self._rng.choice(PARTICLE_CHARS),
                    color=color if self._rng.random() < 0.6 else self._rng.choice(PARTICLE_COLORS),
                )
            )
        if len(self.particles) > self.max_particles:
            self.particles = self.particles[-self.max_particles :]

    def tick(self, dt: float = 0.05, *, gravity: float = 1.6) -> None:
        if dt <= 0:
            return
        for particle in self.particles:
            particle.age += dt
            particle.vy += gravity * dt
            particle.x += particle.vx * dt
            particle.y += particle.vy * dt
        self.particles = [p for p in self.particles if p.alive and p.y >= -1]

    def clear(self) -> None:
        self.particles.clear()

    @property
    def active(self) -> int:
        return len(self.particles)

    def render(self, width: int = 40, height: int = 3) -> Text:
        if not self.particles or height <= 0 or width <= 0:
            return Text("")
        cells: list[list[tuple[str, str] | None]] = [[None] * width for _ in range(height)]
        for particle in self.particles:
            x = int(round(particle.x))
            y = int(round(particle.y))
            if 0 <= x < width and 0 <= y < height:
                cells[y][x] = (particle.char, PARTICLE_COLORS[particle.fade_index])
        lines: list[list[tuple[str, str]]] = []
        for row in cells:
            rendered: list[tuple[str, str]] = []
            for cell in row:
                rendered.append(cell or (" ", "default"))
            lines.append(rendered)
        text = Text()
        for row_index, row in enumerate(lines):
            if row_index:
                text.append("\n")
            for char, color in row:
                text.append(char, style=color)
        return text
