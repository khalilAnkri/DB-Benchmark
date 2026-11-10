ALTER TABLE b.lineitem ADD PRIMARY KEY (l_orderkey, l_linenumber);
ALTER TABLE b.orders   ADD PRIMARY KEY (o_orderkey);
ALTER TABLE b.part     ADD PRIMARY KEY (p_partkey);
VACUUM ANALYZE b.lineitem;
VACUUM ANALYZE b.orders;
VACUUM ANALYZE b.part;
