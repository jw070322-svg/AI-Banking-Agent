#pragma once
#include "account.h"
#include <map>
#include <string>
class Bank {
    std::map<std::string, Record> records;
    std::string path;
    void save(const std::map<std::string, Record>& next);
public:
    explicit Bank(std::string file);
    const Record& get(const std::string& id) const;
    void transact(const std::string& id, int operation, Money amount,
                  const std::string& target = "");
};
