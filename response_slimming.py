#!/usr/bin/env python3
"""Slim projections for MCP list-tool responses.

Basecamp list endpoints return verbose objects: embedded person records
(avatar CDN URLs, attachable SGIDs, permission flags), half a dozen signed
API URL fields per recording, and full dock entries per project. For an LLM
client that is almost entirely dead weight, and on real accounts it pushes
list responses far past what MCP hosts accept as a tool result (issue #36:
get_projects alone was ~84k tokens for 44 projects; the actual payload —
names, descriptions, status, dates — was ~3% of that).

The helpers here project each item down to what an MCP client actually
uses, in the tool layer only: `BasecampClient` keeps returning the raw API
payload, and detail tools (get_project, get_todo, ...) stay full.

Slimming is on by default. Set ``BASECAMP_MCP_FULL_RESPONSES=1`` to restore
the raw API responses on all tools.
"""

import os

FULL_RESPONSES_ENV = 'BASECAMP_MCP_FULL_RESPONSES'

# URL fields are dropped except the ones a client actually consumes:
# the human-clickable app URL, an attachment's download URL (the input for
# the download_attachment tool), and a webhook's configured target.
_KEPT_URL_KEYS = frozenset({'app_url', 'download_url', 'payload_url'})

# References to the containing resource are reduced to a stub.
_CONTAINER_KEYS = frozenset({'parent', 'bucket'})
_CONTAINER_FIELDS = ('id', 'title', 'name', 'type')

# A dict with id + name plus any of these markers is an embedded person.
_PERSON_MARKER_KEYS = ('avatar_url', 'email_address', 'personable_type',
                       'attachable_sgid')

_PROJECT_FIELDS = ('id', 'name', 'description', 'purpose', 'status',
                   'created_at', 'updated_at', 'app_url')


def full_responses_enabled():
    """True when the user opted out of slimming via the environment."""
    value = os.environ.get(FULL_RESPONSES_ENV, '')
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _looks_like_person(value):
    return ('id' in value and 'name' in value
            and any(key in value for key in _PERSON_MARKER_KEYS))


def slim_value(value):
    """Recursively slim any JSON structure returned by the Basecamp API.

    - embedded person objects become ``{id, name}``
    - ``url``/``*_url`` fields are dropped, except ``app_url``
    - ``parent``/``bucket`` references are reduced to id/title/name/type

    Everything else (content, descriptions, dates, counts, ...) passes
    through unchanged.
    """
    if isinstance(value, list):
        return [slim_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if _looks_like_person(value):
        return {'id': value['id'], 'name': value['name']}
    slimmed = {}
    for key, item in value.items():
        if (key == 'url' or key.endswith('_url')) and key not in _KEPT_URL_KEYS:
            continue
        if key in _CONTAINER_KEYS and isinstance(item, dict):
            slimmed[key] = {field: item[field]
                            for field in _CONTAINER_FIELDS if field in item}
            continue
        slimmed[key] = slim_value(item)
    return slimmed


def slim_project(project):
    """Project a full project object to the fields an LLM client uses.

    ``tools`` lists the names of enabled dock entries; ``user_ids`` carries
    the ids from ``people.team.sample`` (names resolve once via
    ``get_people`` instead of repeating full person objects per project).
    """
    dock = project.get('dock') or []
    team = (project.get('people') or {}).get('team') or {}
    slimmed = {field: project.get(field) for field in _PROJECT_FIELDS}
    slimmed['tools'] = [entry['name'] for entry in dock if entry.get('enabled')]
    slimmed['user_ids'] = [person['id'] for person in team.get('sample') or []]
    return slimmed


def maybe_slim(value):
    """Apply the generic slim projection unless full responses are enabled."""
    if full_responses_enabled():
        return value
    return slim_value(value)


def maybe_slim_projects(projects):
    """Apply the project projection unless full responses are enabled."""
    if full_responses_enabled():
        return projects
    return [slim_project(project) for project in projects]


def maybe_slim_search_results(results):
    """Slim a search-results mapping.

    Applies the project projection to a ``projects`` key and the generic
    recipe to every other result list.
    """
    if full_responses_enabled():
        return results
    return {
        key: ([slim_project(item) for item in items]
              if key == 'projects' and isinstance(items, list)
              else slim_value(items))
        for key, items in results.items()
    }
