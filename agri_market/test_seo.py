from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(SITE_URL="https://thin-dee.onrender.com")
class SearchDiscoveryTests(TestCase):
    def test_robots_points_crawlers_to_the_public_sitemap(self):
        response = self.client.get(reverse("robots_txt"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertContains(response, "Allow: /")
        self.assertContains(response, "Disallow: /admin/")
        self.assertContains(response, "Sitemap: https://thin-dee.onrender.com/sitemap.xml")

    def test_sitemap_lists_public_pages_with_canonical_urls(self):
        response = self.client.get(reverse("sitemap_xml"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml; charset=utf-8")
        self.assertContains(response, "https://thin-dee.onrender.com/")
        self.assertContains(response, "https://thin-dee.onrender.com/privacy/")
        self.assertNotContains(response, "/admin/")