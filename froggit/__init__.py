#!/usr/bin/env python

from __future__ import print_function
import os, imp, collections, shutil
import jinja2, markdown, yaml
from . import six
from markdown.extensions.meta import MetaExtension

TMP_TEMPLATE = """
{{% extends '{0}' %}}
{{% block {1} %}}
{2}
{{% endblock %}}
"""

def deep_update(dict1, dict2):
	for k, v in dict2.items():
		if isinstance(v, collections.Mapping):
			r = deep_update(dict1.get(k, {}), v)
			dict1[k] = r
		else:
			dict1[k] = v
	return dict1

class Site(object):

	default_settings = {
		"environment": {
			"views": "views.yaml",
			"pages": "pages",
			"templates": "templates",
			"assets": "assets"
		},
		"default_block": "content"
	}

	def __init__(self, environment="."):

		self.environment = os.path.abspath(environment)
		self.settings = dict(self.default_settings)
		try:
			with open(os.path.join(self.environment, "settings.yaml")) as settings_file:
				settings = yaml.load(settings_file)
				deep_update(self.settings, settings)
		except IOError:
			pass

		self.templates = jinja2.Environment(loader=jinja2.FileSystemLoader(os.path.join(self.environment, "templates")))
		with open(os.path.join(self.environment, self.settings["environment"]["views"])) as vstream:
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
			if view.get("subviews"):
				routeList += self._routes(views=view["subviews"])
			else:
				routeList.append(view["full_route"])

		return routeList

	def set_full_routes(self, views=None, route_prefix="/"):
		"""set full routes for each view"""

		views = views or self.views

		for view in views:
			view["full_route"] = route_prefix + view["route"]
			if view.get("subviews"):
				self.set_full_routes(views=view["subviews"], route_prefix = view["full_route"] + "/")

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

			if view.get("subviews"):
				self.set_templates(views=view["subviews"], template=view["template"])

	def build(self, out="", views=None):

		out = out or os.path.join(self.environment, "distribute")
		if os.path.abspath(out) == os.path.abspath(self.environment):
			raise OSError("Cannot build site in source directory")

		try:
			os.listdir(out)
		except OSError:
			os.mkdir(out)
		else:
			shutil.rmtree(out)
			os.mkdir(out)

		views = views or self.views

		md = markdown.Markdown(extensions=[MetaExtension()])

		for view in views:
			if view.get("subviews"):
				new_out = os.path.join(out, view["route"])
				self.build(out=new_out, views=view["subviews"])
				continue

			context = dict(route=view["full_route"], db=self.db, **view.get("context", {}))

			page_fnames = view.get("pages", ["".join(view["full_route"].lstrip("/").split(".")[:-1]) + ".md"])

			if not isinstance(page_fnames, collections.Iterable) or isinstance(page_fnames, six.string_types):
				page_fnames = [page_fnames]

			page_fnames = [os.path.join(
				self.environment,
				self.settings["environment"]["pages"],
				fname
			) for fname in page_fnames]

			with open(os.path.join(out, view["route"]), "w") as out_file:
				try:
					blocks = {}
					tmp_template = "{{% extends '{0}' %}}".format(view["template"])

					for page_fname in page_fnames:
						with open(page_fname, "r") as page_file:
							html = md.convert(page_file.read())
							meta = {}
							special = {}

							for k, v in md.Meta.items():
								# double-underscore vars are special vars used by froggit
								if k == "__block__":
									d = special
								else:
									d = meta

								if len(v) == 1:
									d[k] = v[0]
								else:
									d[k] = v

							context.update(meta)

							block_name = special.get("__block__", self.settings["default_block"])
							blocks[block_name] = html
							tmp_template += "{{% block {0}%}}{1}{{% endblock %}}".format(block_name, html)

					with open(os.path.join(self.environment, "templates", "_tmp.html"), "w") as tmp:
						tmp.write(tmp_template)
					template = self.templates.get_template("_tmp.html")
					out_file.write(template.render(**context))
				except IOError:
					template = self.templates.get_template(view["template"])
					out_file.write(template.render(**context))

		#skip asset copying if this is not the top level of the recursive build
		if views != self.views:
			return
		try:
			assets_folder = os.path.join(self.environment, self.settings["environment"]["assets"])
			for f in os.listdir(assets_folder):
				if os.path.isdir(os.path.join(assets_folder, f)):
					shutil.copytree(os.path.join(assets_folder, f), os.path.join(out, f))
				else:
					shutil.copy(os.path.join(assets_folder, f), out)
		except OSError:
			pass
