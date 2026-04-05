"""SEO route installers for shared Flask apps."""

from __future__ import annotations

import flask

from ._app_specs import SeoRoutesSpec


def install_seo_routes(app: flask.Flask, spec: SeoRoutesSpec) -> None:
    @app.route(f"{spec.url_prefix}/sitemap.xml")
    def sitemap() -> flask.Response:
        response = flask.make_response(spec.sitemap_builder())
        response.headers["Content-Type"] = "application/xml; charset=utf-8"
        response.headers["Cache-Control"] = f"public, max-age={spec.sitemap_cache_max_age}"
        return response

    @app.route(f"{spec.url_prefix}/robots.txt")
    def robots() -> flask.Response:
        response = flask.make_response(spec.robots_builder())
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        response.headers["Cache-Control"] = f"public, max-age={spec.robots_cache_max_age}"
        return response

    image_builder = spec.image_sitemap_builder
    if image_builder is None:
        return

    @app.route(f"{spec.url_prefix}/sitemap-images.xml")
    def sitemap_images() -> flask.Response:
        response = flask.make_response(image_builder())
        response.headers["Content-Type"] = "application/xml; charset=utf-8"
        response.headers["Cache-Control"] = f"public, max-age={spec.image_sitemap_cache_max_age}"
        return response
