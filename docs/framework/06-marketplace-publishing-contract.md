# 06: Marketplace Publishing Contract

Status: Done

## Goal

Define how node packages and workflow assets are exported into `bpg-marketplace` as machine-readable artifacts.

## Scope

- Artifact generation
- Schema validation
- Publish and sync workflow

## Implementation

Generate marketplace metadata for node packages, templates, and packs from framework package manifests. The exporter maps framework-owned metadata into marketplace-facing fields such as capability taxonomy, compatibility constraints, trust metadata, installation commands, and documentation pointers.

Add commands for export, validation, and sync. Sync should open or update registry artifacts against the marketplace repository rather than publishing runnable code there directly. The framework remains responsible for generating the machine-readable description of an installable package; package distribution stays with the package index or source repository referenced by that metadata.

Generated artifacts must validate against the marketplace repository schemas before publish or sync operations succeed. Keep artifact generation deterministic so metadata snapshots are reviewable in pull requests.

## Public Interfaces

- `bpg marketplace export`
- `bpg marketplace validate`
- Artifact file layout aligned to the marketplace repository design

## Test Plan

- Schema validation against marketplace schemas
- Snapshot tests for generated metadata
- Sync dry-run tests
- Virtualenv-based packaging tests using `uv`

## Acceptance Criteria

- Framework packages emit marketplace-ready metadata
- Generated artifacts fit the model of registry metadata plus external package installation
- Validation failures block publish and sync flows

## Out of Scope

- Hosting package artifacts inside the marketplace repo
- Defining a new registry model separate from `bpg-marketplace`
- Non-deterministic or manual-only publish flows
