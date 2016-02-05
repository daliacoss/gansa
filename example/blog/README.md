Setup
-----

This project is intended to be used with a SQL database. Create a user.yaml file to specify the database settings. An example user.yaml file is provided.

Creating a post
---------------

To create a new blog post, create a Markdown file for it in the pages folder, then add a view for it in views.yaml. After this, when you build the site, you will be asked if you want to publish the new post. Entering "y" or "yes" will add the post to the database, set its date of publication, and allow it to be listed in the blog index.

For example, if you wanted to create a post called "My Third Post", you could save the following as src/pages/mythirdpost.md:

```
author: Somebody
title: My Third Post

This is my third post!
```

Then add the following line ot the end of views.yaml (note the indent):

```
    - route: mythirdpost.html
```

Commentary
----------

This project is intended to demonstrate how callback functions can be used to extend Froggit's functionality. A post is "published" whenever a reference to it is added to the project's database.

Whenever the context processor is called for each post, it adds a flag to a global table if it cannot find a reference to the post in the database. Then, once all views are rendered, the postrender function goes through each flagged post in the public table and asks the user if they wish to publish the post. The next time the site is rendered, the newly published posts will display their publication dates and be listed on the blog index page.

One weakness of this example is that the site must be rendered twice every time posts are published. To compensate, the postrender function automatically re-renders the site when the user publishes a post.