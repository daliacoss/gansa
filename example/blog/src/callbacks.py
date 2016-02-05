import models
import datetime
from froggit.six.moves import input

def blog_post(context, view, site):

    post = site.db.query(models.BlogPost).filter_by(url=view["route"]).first()
    context = dict(context)

    if not post:
        # use site.g to store data that will be shared with other callbacks
        site.g["unpublished_posts"] = site.g.get("unpublished_posts", [])
        site.g["unpublished_posts"].append({"url": view["route"]})
    else:
        context["date_published"] = post.date_published

    return context

def blog_index(context, view, site):

    posts = site.db.query(models.BlogPost).order_by(models.BlogPost.date_published.desc()).all()
    context = dict(context)

    context["posts"] = posts
    return context

def postrender(site, build_args):

    unpublished = site.g.get("unpublished_posts", [])
    num_published = 0

    for post in unpublished:

        response = ""
        while not response:
            response = input("Unpublished post '{0}' found. Publish this post? (y/n) ".format(post["url"]))
            response = {"y":"yes", "yes":"yes", "n":"no", "no":"no"}.get(response.lower(), "")

        if response == "yes":
            record = models.BlogPost(url=post["url"], date_published=datetime.datetime.now())
            site.db.add(record)
            site.db.commit()
            num_published += 1

    if num_published:
        # rerender the site so published posts will include dates
        site.build(**build_args)