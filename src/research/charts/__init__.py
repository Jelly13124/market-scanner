"""Matplotlib chart pipeline for the SOP Technical section.

Public API lives in ``render``: K-line PNG, equity-curve PNG, and a
base64 data-URI variant of the equity curve for inline email embedding.

Matplotlib is forced onto the headless ``Agg`` backend at module load
(see ``render`` module top) so this works on Windows servers without a
display.
"""
