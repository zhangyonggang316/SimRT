# SOEM dependency

The runtime builds against the pinned upstream SOEM v1.4.0 source tree in
`soem/`. Source: https://github.com/OpenEtherCATsociety/SOEM/tree/v1.4.0
Its upstream license is retained in `soem/LICENSE`. SOEM v1.4.0 is GPLv2 with
the SOEM exception; review that license before distributing a linked product.
The MATLAB build compiles SOEM into the generated target executable; no
target-side shared library installation or raw Ethernet reimplementation is used.

Upstream v1.4.0 archive SHA-256:
`91a9c7cc470c63fc3e0b19a3aedba6a01641e254127108575445face948bc2ae`.
