<!-- Made from terms.yaml beside this file by the glossary hook of murphy360/standards. Do not edit it:
     change terms.yaml, then run `pre-commit run glossary --all-files`. -->

# Glossary

The terms this project uses, A to Z. Each is defined once, in `terms.yaml` beside this page.

## Definition of done

What a pull request holds before it merges: the code, its tests, the docs it changes, and a green CI run.

See also: [Standard](#standard).

## Garage

Where the flags are kept and where every run starts and ends. Set with --garage.

## Leg

A stretch of a zone, three to eight stops long, that fits in one Google Maps link. The link starts navigation from the phone's own location.

See also: [Zone](#zone).

## Override

A hand fix in overrides.csv: a corrected street and town, fixed map coordinates, or both, for a stop the source list gets wrong. Each one shows on the Data issues list with its note.

Also called: hand fix.

## Route

One tab of the source workbook ("Route N"): the stops one family handled, in the order they were listed.

See also: [Zone](#zone).

## Run

One trip to install or to remove the flags of a zone for one holiday.

## Standard

The shared rules every murphy360 project follows (murphy360/standards): the checks CI runs, the templates, and the instructions agents read.

Also called: murphy360/standards.

## Stop

One address on a route or zone. It may take more than one flag.

## Zone

The planner's proposed version of a route: the stops one family installs and removes, in driving order from the garage and back. Zone N starts from Route N, so families keep the streets they know.

See also: [Route](#route), [Leg](#leg), [Garage](#garage).

## Other names

Each other name, and the term it means.

- hand fix: [Override](#override)
- murphy360/standards: [Standard](#standard)
