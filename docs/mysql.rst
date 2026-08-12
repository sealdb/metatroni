.. _mysql:

==============================
MySQL high-availability support
==============================

.. warning::

   MySQL support is under active development and is **not yet recommended for
   production use**.

This chapter describes Patroni's MySQL backend: how it fits into the HA loop,
how replication modes work, and how to deploy and operate a cluster.

.. toctree::
   :maxdepth: 2

   mysql_architecture
   mysql_mechanisms
   mysql_ops

What you get
============

With ``database.type: mysql``, each node runs Patroni + ``mysqld``. Patroni:

- Holds / races for a **leader lease** in the DCS (etcd, Consul, ZooKeeper, …)
- Monitors MySQL health and publishes status (including GTID) to the DCS
- Manages **async GTID**, **semi-sync**, or **Group Replication (MGR)**
- Clones replicas via ``mysqldump`` or ``xtrabackup``
- Exposes the usual REST API and ``patronictl`` surface

Quick start
===========

.. code-block:: shell

    pip install 'patroni[mysql,etcd3]'

    patroni_mysql_init -o deploy/mysql-ha --force \
      --bin-dir /usr/local/mysql/bin --mode semi-sync --nodes 3

    # start etcd, then:
    ./deploy/mysql-ha/start.sh
    patronictl -c deploy/mysql-ha/mysql0/patroni.yml list
    haproxy -f deploy/mysql-ha/haproxy.cfg -db   # optional :5000 / :5001

Read next
=========

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * - Page
     - Focus
     - Start here if you need…
   * - :ref:`mysql_architecture`
     - Components, DCS model, vs PostgreSQL
     - System design / code map
   * - :ref:`mysql_mechanisms`
     - Failover, demote, semi-sync, MGR, clone
     - “How does it work?”
   * - :ref:`mysql_ops`
     - Install, day-2, FAQ
     - Deploy / troubleshoot
