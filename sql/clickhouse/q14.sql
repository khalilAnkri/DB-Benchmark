SELECT toDecimal128(100, 12) * sum(CASE WHEN p_type LIKE 'PROMO%'
                                        THEN l_extendedprice * (1 - l_discount) ELSE 0 END)
       / sum(l_extendedprice * (1 - l_discount)) AS promo_revenue
FROM lineitem
JOIN part ON p_partkey = l_partkey
WHERE l_shipdate >= toDate('1995-09-01') AND l_shipdate < toDate('1995-10-01');
