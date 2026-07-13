#!/usr/bin/env python3
"""Tests for the slim response projections (issue #36).

List tools project Basecamp API payloads down to what an MCP client
actually uses: embedded person objects become ``{id, name}``, signed URL
fields are dropped (except the human-clickable ``app_url``), and
``parent``/``bucket`` references shrink to a stub. ``get_projects`` uses a
dedicated projection (``tools`` from enabled dock entries, ``user_ids``
from the team sample). ``BASECAMP_MCP_FULL_RESPONSES=1`` restores the raw
payloads.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from response_slimming import (
    FULL_RESPONSES_ENV,
    full_responses_enabled,
    maybe_slim,
    maybe_slim_projects,
    maybe_slim_search_results,
    slim_project,
    slim_value,
)


def _project():
    """A realistic (abridged) project object from GET /projects.json."""
    return {
        'id': 46996967,
        'status': 'active',
        'created_at': '2026-04-22T15:21:34.256Z',
        'updated_at': '2026-07-08T09:00:16.212Z',
        'name': 'example/project',
        'description': 'Project description',
        'purpose': 'topic',
        'clients_enabled': False,
        'bookmark_url': 'https://3.basecampapi.com/195539477/my/bookmarks/BAh0b2tlbg.json',
        'url': 'https://3.basecampapi.com/195539477/projects/46996967.json',
        'app_url': 'https://3.basecamp.com/195539477/projects/46996967',
        'dock': [
            {'id': 1, 'title': 'Message Board', 'name': 'message_board',
             'enabled': True, 'position': 1,
             'url': 'https://3.basecampapi.com/x.json', 'app_url': 'https://3.basecamp.com/x'},
            {'id': 2, 'title': 'Schedule', 'name': 'schedule',
             'enabled': False, 'position': None,
             'url': 'https://3.basecampapi.com/y.json', 'app_url': 'https://3.basecamp.com/y'},
            {'id': 3, 'title': 'Card Table', 'name': 'kanban_board',
             'enabled': True, 'position': 2,
             'url': 'https://3.basecampapi.com/z.json', 'app_url': 'https://3.basecamp.com/z'},
        ],
        'people': {
            'team': {
                'count': 2,
                'sample': [
                    {'id': 52219584, 'name': 'Amy Rivera',
                     'avatar_url': 'https://cdn.example/avatar1'},
                    {'id': 51529649, 'name': 'Victor Cooper',
                     'avatar_url': 'https://cdn.example/avatar2'},
                ],
            },
        },
    }


class TestSlimProject(unittest.TestCase):
    """slim_project() applies the projection proposed in issue #36."""

    def test_projects_to_issue_contract(self):
        """Only the agreed fields survive; tools/user_ids are derived."""
        self.assertEqual(slim_project(_project()), {
            'id': 46996967,
            'name': 'example/project',
            'description': 'Project description',
            'purpose': 'topic',
            'status': 'active',
            'created_at': '2026-04-22T15:21:34.256Z',
            'updated_at': '2026-07-08T09:00:16.212Z',
            'app_url': 'https://3.basecamp.com/195539477/projects/46996967',
            'tools': ['message_board', 'kanban_board'],
            'user_ids': [52219584, 51529649],
        })

    def test_tolerates_missing_dock_and_people(self):
        """Minimal project objects do not raise."""
        slimmed = slim_project({'id': 1, 'name': 'bare'})
        self.assertEqual(slimmed['tools'], [])
        self.assertEqual(slimmed['user_ids'], [])


class TestSlimValue(unittest.TestCase):
    """slim_value() is the generic recipe for all other list tools."""

    def test_drops_url_fields_except_app_url(self):
        slimmed = slim_value({
            'id': 1,
            'url': 'https://3.basecampapi.com/x.json',
            'app_url': 'https://3.basecamp.com/x',
            'bookmark_url': 'https://3.basecampapi.com/bookmark',
            'subscription_url': 'https://3.basecampapi.com/subscription',
            'title': 'A todo',
        })
        self.assertEqual(slimmed, {
            'id': 1,
            'app_url': 'https://3.basecamp.com/x',
            'title': 'A todo',
        })

    def test_keeps_consumable_url_fields(self):
        """download_url (attachment input) and payload_url (webhook target)
        are payload, not decoration, and must survive slimming."""
        attachment = {'id': 1, 'download_url': 'https://storage.example/f.pdf',
                      'preview_url': 'https://storage.example/f-preview.png'}
        webhook = {'id': 2, 'payload_url': 'https://example.com/hook',
                   'url': 'https://3.basecampapi.com/w.json'}
        self.assertEqual(slim_value(attachment),
                         {'id': 1, 'download_url': 'https://storage.example/f.pdf'})
        self.assertEqual(slim_value(webhook),
                         {'id': 2, 'payload_url': 'https://example.com/hook'})

    def test_compacts_embedded_person_objects(self):
        """Persons (detected via marker keys) shrink to {id, name}."""
        todo = {
            'id': 1,
            'creator': {'id': 2, 'name': 'Amy Rivera',
                        'attachable_sgid': 'BAh7...', 'admin': False,
                        'avatar_url': 'https://cdn.example/a'},
            'assignees': [
                {'id': 3, 'name': 'Victor Cooper',
                 'email_address': 'victor@example.com', 'admin': True},
            ],
        }
        slimmed = slim_value(todo)
        self.assertEqual(slimmed['creator'], {'id': 2, 'name': 'Amy Rivera'})
        self.assertEqual(slimmed['assignees'], [{'id': 3, 'name': 'Victor Cooper'}])

    def test_keeps_non_person_dicts_with_id_and_name(self):
        """A dict with id+name but no person markers is not compacted."""
        column = {'id': 9, 'name': 'In Progress', 'color': 'blue'}
        self.assertEqual(slim_value(column), column)

    def test_reduces_parent_and_bucket_to_stub(self):
        slimmed = slim_value({
            'id': 1,
            'parent': {'id': 7, 'title': 'A list', 'type': 'Todolist',
                       'url': 'https://3.basecampapi.com/p.json',
                       'app_url': 'https://3.basecamp.com/p'},
            'bucket': {'id': 8, 'name': 'A project', 'type': 'Project'},
        })
        self.assertEqual(slimmed['parent'],
                         {'id': 7, 'title': 'A list', 'type': 'Todolist'})
        self.assertEqual(slimmed['bucket'],
                         {'id': 8, 'name': 'A project', 'type': 'Project'})

    def test_preserves_content_and_scalars(self):
        """Actual payload (content, counts, dates, strings) is untouched."""
        value = {'content': '<p>See https://example.com/url</p>',
                 'comments_count': 3, 'due_on': '2026-08-01',
                 'completed': False, 'ratio': 0.5, 'note': None}
        self.assertEqual(slim_value(value), value)

    def test_recurses_into_nested_lists(self):
        board = {'lists': [{'id': 1, 'subscribers': [
            {'id': 2, 'name': 'Amy', 'avatar_url': 'https://cdn.example/a'}]}]}
        slimmed = slim_value(board)
        self.assertEqual(slimmed['lists'][0]['subscribers'],
                         [{'id': 2, 'name': 'Amy'}])


class TestOptOut(unittest.TestCase):
    """BASECAMP_MCP_FULL_RESPONSES=1 restores raw payloads everywhere."""

    def test_env_values(self):
        for raw, expected in [('1', True), ('true', True), ('YES', True),
                              ('on', True), ('', False), ('0', False),
                              ('off', False)]:
            with patch.dict(os.environ, {FULL_RESPONSES_ENV: raw}):
                self.assertEqual(full_responses_enabled(), expected, raw)

    def test_maybe_helpers_pass_through_when_enabled(self):
        project = _project()
        recording = {'id': 1, 'url': 'https://3.basecampapi.com/x.json'}
        results = {'projects': [project]}
        with patch.dict(os.environ, {FULL_RESPONSES_ENV: '1'}):
            self.assertIs(maybe_slim_projects([project])[0], project)
            self.assertIs(maybe_slim(recording), recording)
            self.assertIs(maybe_slim_search_results(results), results)

    def test_maybe_helpers_slim_by_default(self):
        with patch.dict(os.environ, {FULL_RESPONSES_ENV: ''}):
            self.assertNotIn('url', maybe_slim(
                {'id': 1, 'url': 'https://3.basecampapi.com/x.json'}))
            self.assertEqual(maybe_slim_projects([_project()])[0]['tools'],
                             ['message_board', 'kanban_board'])


class TestSearchResults(unittest.TestCase):
    """Search tools slim their aggregated result mapping."""

    def test_projects_key_uses_project_projection(self):
        results = maybe_slim_search_results({
            'projects': [_project()],
            'todos': [{'id': 1, 'url': 'https://3.basecampapi.com/t.json',
                       'title': 'A todo'}],
        })
        self.assertEqual(results['projects'][0]['tools'],
                         ['message_board', 'kanban_board'])
        self.assertEqual(results['todos'], [{'id': 1, 'title': 'A todo'}])


if __name__ == '__main__':
    unittest.main()
