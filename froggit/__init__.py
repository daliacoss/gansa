#!/usr/bin/env python

from __future__ import print_function
import os, imp, jinja2, markdown, yaml
from markdown.extensions.meta import MetaExtension

TMP_TEMPLATE = """
{{% extends '{0}' %}}
{{% block {1} %}}
{2}
{{% endblock %}}
"""

class Site(object):

	def __init__(self, environment="."):

		self.environment = os.path.abspath(environment)
		self.templates = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(self.environment, "templates")))
		with open(os.path.join(self.environment, "views.yaml")) as vstream:
			self.views = yaml.load(vstream)
		self.db = {}

		self.set_full_routes()
		self.set_templates()

	@property
	def routes(self):
		return self._routes()

	def _routes(self, views=None):

		routeList = []

		views = views or self.views

		for view in views:
			if view.get("pages"):
				routeList += self._routes(views=view["pages"])
			else:
				routeList.append(view["full_route"])

		return routeList

	def set_full_routes(self, views=None, route_prefix="/"):
		"""set full routes for each view"""

		views = views or self.views

		for view in views:
			view["full_route"] = route_prefix + view["route"]
			if view.get("pages"):
				self.set_full_routes(views=view["pages"], route_prefix = view["full_route"] + "/")

	def set_templates(self, views=None, template=""):
		"""
		explicitly set templates for each view.

		if a view template is not explicitly defined, refer to the nearest
		ancestor with an explicitly defined template.
		"""

		views = views or self.views

		for view in views:
			if not view.get("template"):
				view["template"] = template

			if view.get("pages"):
				self.set_templates(views=view["pages"], template=view["template"])

	def build(self, out="", views=None):

		out = out or os.path.join(self.environment, "distribute")
		try:
			os.listdir(out)
		except OSError:
			os.mkdir(out)

		views = views or self.views

		md = markdown.Markdown(extensions=[MetaExtension()])

		for view in views:
			if view.get("pages"):
				new_out = os.path.join(out, view["route"])
				self.build(out=new_out, views=view["pages"])
			else:
				context = dict(route=view["full_route"], **view.get("context", {}))
				page_fname = os.path.join(
					self.environment,
					"pages",
					"".join(view["full_route"].lstrip("/").split(".")[:-1]) + ".md"
				)

				with open(os.path.join(out, view["route"]), "w") as out_file:
					try:
						with open(page_fname, "r") as page_file:
							html = md.convert(page_file.read())
							meta = {}
							for k, v in md.Meta.items():
								if len(v) == 1:
									meta[k] = v[0]
								else:
									meta[k] = v
							context.update(meta)

							with open(os.path.join(self.environment, "templates", "_tmp.html"), "w") as tmp:
								tmp.write(TMP_TEMPLATE.format(view["template"], meta.get("__block__", "content"), html))
							template = self.templates.get_template("_tmp.html")
							out_file.write(template.render(**context))
					except IOError:
						template = self.templates.get_template(view["template"])
						out_file.write(template.render(**context))
