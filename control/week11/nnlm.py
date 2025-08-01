#coding:utf8

import torch
import torch.nn as nn
import numpy as np
import math
import random
import os
import re
import json

from sympy import false
from torch.linalg import diagonal
from transformers import BertModel,BertTokenizer,BertConfig

"""
基于pytorch的LSTM语言模型
"""
seed = 5
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)
torch.cuda.manual_seed_all(seed)


class LanguageModel(nn.Module):
    def __init__(self, config = None):
        super(LanguageModel, self).__init__()
        # self.embedding = nn.Embedding(len(vocab), input_dim)
        # self.layer = nn.LSTM(input_dim, input_dim, num_layers=1, batch_first=True)
        self.config = config
        decoder_config = BertConfig( vocab_size= config["vocab_size"],is_decoder=True, add_cross_attention=True)
        self.bert = BertModel.from_pretrained(r"E:\BaiduNetdiskDownload\八斗nlp\week6\bert-base-chinese\bert-base-chinese",config = decoder_config)
        self.classify = nn.Linear( config["hidden_size"]  , config["vocab_size"])
        self.dropout = nn.Dropout(0.1)
        self.loss = nn.functional.cross_entropy  # 交叉熵

    #当输入真实标签，返回loss值；无真实标签，返回预测值
    def forward(self, x, y=None, is_sft = False):

        #  attention_mask (`torch.FloatTensor` of shape `(batch_size, sequence_length)` or `(batch_size, sequence_length, target_length)`, *optional*):
        #    Mask to avoid performing attention on the padding token indices of the encoder input. This mask is used in
        #    the cross-attention if the model is configured as a decoder. Mask values selected in `[0, 1]`:
        if not is_sft:
            if y is not None:
                x = self.bert(input_ids=x, attention_mask=generate_square_subsequent_mask(self.config["batch_size"],
                                                                                          self.config["window_size"]))[
                    0]  # output shape:(batch_size, sen_len, hidden_size )
                y_pred = self.classify(x)  # output shape:(batch_size, sen_len, vocab_size)
                return self.loss(y_pred.view(-1, y_pred.shape[-1]), y.view(-1))
            else:
                x = self.bert(input_ids=x)[0]  # output shape:(batch_size, sen_len, hidden_size )
                y_pred = self.classify(x)  # output shape:(batch_size, sen_len, vocab_size)
                return torch.softmax(y_pred, dim=-1)
        else:
            # sft ，需要引入 新的 mask，
            mask = torch.tril(torch.ones((x.shape[0], x.shape[1], x.shape[1])))
            mask[:,0:self.config["title_size"],:] = 0
            x = self.bert(input_ids=x, attention_mask=mask)[0]  # output shape:(batch_size, sen_len, hidden_size )
            y_pred = self.classify(x)  # output shape:(batch_size, sen_len, vocab_size)
            if y is not None:
                return self.loss(y_pred.view(-1, y_pred.shape[-1])[self.config["title_size"]:], y.view(-1)[self.config["title_size"]:])
            else:
                return torch.softmax(y_pred, dim=-1)[:,self.config["title_size"]:,:]

def  generate_square_subsequent_mask(batch_size, sz): # batch 64, sz 10, 10
        attn_shape = (batch_size , sz , sz)
        mask = (torch.triu(torch.ones(attn_shape),diagonal = 1))
        return mask == 0

#加载字表
def build_vocab(vocab_path):
    vocab = {"<pad>":0}
    with open(vocab_path, encoding="utf8") as f:
        for index, line in enumerate(f):
            char = line[:-1]       #去掉结尾换行符
            vocab[char] = index + 1 #留出0位给pad token
    return vocab

#加载语料
def load_corpus(path):
    corpus = ""
    with open(path, encoding="gbk") as f:
        for line in f:
            corpus += line.strip()
    return corpus

#随机生成一个样本
#从文本中截取随机窗口，前n个字作为输入，最后一个字作为输出
def build_sample(vocab, window_size, corpus):
    start = random.randint(0, len(corpus) - 1 - window_size)
    end = start + window_size
    window = corpus[start:end]
    target = corpus[start + 1:end + 1]  #输入输出错开一位
    # print(window, target)
    x = [vocab.get(word, vocab["[UNK]"]) for word in window]   #将字转换成序号
    y = [vocab.get(word, vocab["[UNK]"]) for word in target]
    return x, y

#建立数据集
#sample_length 输入需要的样本数量。需要多少生成多少
#vocab 词表
#window_size 样本长度
#corpus 语料字符串
def build_dataset(sample_length, vocab, window_size, corpus):
    dataset_x = []
    dataset_y = []
    for i in range(sample_length):
        x, y = build_sample(vocab, window_size, corpus)
        dataset_x.append(x)
        dataset_y.append(y)
    return torch.LongTensor(dataset_x), torch.LongTensor(dataset_y)


#建立模型
def build_model(config):

    config["hidden_size"] = 768
    model = LanguageModel(config)
    return model

#文本生成测试代码
def generate_sentence(openings, model, vocab, window_size):
    reverse_vocab = dict((y, x) for x, y in vocab.items())
    model.eval()
    with torch.no_grad():
        pred_char = ""
        #生成了换行符，或生成文本超过30字则终止迭代
        while pred_char != "\n" and len(openings) <= 30:
            openings += pred_char
            x = [vocab.get(char, vocab["[UNK]"]) for char in openings[-window_size:]]
            x = torch.LongTensor([x])
            if torch.cuda.is_available():
                x = x.cuda()
            y = model(x, is_sft = False)[0][-1]
            index = sampling_strategy(y)
            pred_char = reverse_vocab[index]
    return openings

def generate_replay(openings, model, vocab, window_size):
    reverse_vocab = dict((y, x) for x, y in vocab.items())
    model.eval()
    with torch.no_grad():
        pred_char = ""
        #生成了换行符，或生成文本超过30字则终止迭代
        while pred_char != "\n" and len(openings) <= 30:
            openings += pred_char
            x = [vocab.get(char, vocab["[UNK]"]) for char in openings[-window_size:]]
            x = torch.LongTensor([x])
            if torch.cuda.is_available():
                x = x.cuda()
            y = model(x, is_sft = True)[0][-1]
            index = sampling_strategy(y)
            pred_char = reverse_vocab[index]
    return openings

def sampling_strategy(prob_distribution):
    if random.random() > 0.1:
        strategy = "greedy"
    else:
        strategy = "sampling"

    if strategy == "greedy":
        return int(torch.argmax(prob_distribution))
    elif strategy == "sampling":
        prob_distribution = prob_distribution.cpu().numpy()
        return np.random.choice(list(range(len(prob_distribution))), p=prob_distribution)


#计算文本ppl
def calc_perplexity(sentence, model, vocab, window_size):
    prob = 0
    model.eval()
    with torch.no_grad():
        for i in range(1, len(sentence)):
            start = max(0, i - window_size)
            window = sentence[start:i]
            x = [vocab.get(char, vocab["[UNK]"]) for char in window]
            x = torch.LongTensor([x])
            target = sentence[i]
            target_index = vocab.get(target, vocab["[UNK]"])
            if torch.cuda.is_available():
                x = x.cuda()
            pred_prob_distribute = model(x)[0][-1]
            target_prob = pred_prob_distribute[target_index]
            prob += math.log(target_prob, 10)
    return 2 ** (prob * ( -1 / len(sentence)))

def load_sft_data(sft_path):
    data = []
    max_title = 0
    with open(sft_path, encoding="utf8") as f:
        for i, line in enumerate(f):
            line = json.loads(line)
            title = line["title"]
            content = line["content"]
            data.append(line)
            max_title = max(max_title, len(title))
    return data, max_title

#随机生成一个样本
#从文本中截取随机窗口，前n个字作为输入，最后一个字作为输出
def build_sft_sample(vocab, window_size, title_size, title, content):
    # 计算输入数据的位置  title + content  和 window_size 比较
    # 假设，所有数据的 title 都会长于 windows_size ，不然这条数据没有训练意义了。
    diff = window_size -  title_size - 1
    title = [word for word in title]
    content = [word for word in content]
    new_title = title[0:title_size] + ["<sep>"] + content[0:diff]
    new_content = title[0:title_size] + content[0:diff] + ["eos"]
    x = [vocab.get(word, vocab["[UNK]"]) for word in new_title]   #将字转换成序号
    y = [vocab.get(word, vocab["[UNK]"]) for word in new_content]
    return len(title) , x , y
#建立数据集
#sample_length 输入需要的样本数量。需要多少生成多少
#vocab 词表
#window_size 样本长度
#corpus 语料字符串
def build_sft_dataset(sample_length, vocab, window_size, title_size, sft_corpus):
    dataset_x = []
    dataset_y = []
    for i in range(sample_length):
        random_index = random.randint(0, len(sft_corpus) - 1)
        line = sft_corpus[0][random_index]
        _, x, y = build_sft_sample(vocab, window_size,title_size, line["title"], line["content"] )
        dataset_x.append(x)
        dataset_y.append(y)
    return torch.LongTensor(dataset_x), torch.LongTensor(dataset_y)

def train(vocab, corpus_path, save_weight=True):
    config = {}
    config["batch_size"] = 64
    config["vocab_size"]  = len(vocab)
    config["window_size"]  = 10
    config["title_size"] = 5
    epoch_num = 20        #训练轮数
    batch_size = 64       #每次训练样本个数
    train_sample = 50   #每轮训练总共训练的样本总数
    #char_dim = 256        #每个字的维度， 这里由 bert模型内指定，也就是，E:\BaiduNetdiskDownload\八斗nlp\week6\bert-base-chinese\bert-base-chinese 中的 config.json 文件 中的 hidden_size决定
    window_size = 20       #样本文本长度
    title_size = 12
    # vocab = build_vocab("vocab.txt")       #使用 bert的字典表
    corpus = load_corpus(corpus_path)     #加载语料
    model = build_model(config)    #建立模型
    if torch.cuda.is_available():
        model = model.cuda()
    optim = torch.optim.Adam(model.parameters(), lr=0.01)   #建立优化器
    print("文本词表模型加载完毕，开始训练")
    for epoch in range(epoch_num):
        model.train()
        watch_loss = []
        for batch in range(int(train_sample / batch_size)):
            x, y = build_dataset(batch_size, vocab, window_size, corpus) #构建一组训练样本
            if torch.cuda.is_available():
                x, y = x.cuda(), y.cuda()
            optim.zero_grad()    #梯度归零
            loss = model(x, y, false)   #计算loss
            loss.backward()      #计算梯度
            optim.step()         #更新权重
            watch_loss.append(loss.item())
        print("=========\n第%d轮平均loss:%f" % (epoch + 1, np.mean(watch_loss)))
        print(generate_sentence("让他在半年之前，就不能做出", model, vocab, window_size))
        print(generate_sentence("李慕站在山路上，深深的呼吸", model, vocab, window_size))

    print("开始微调！")

    sft_epoch_num = 100       #训练轮数
    sft_train_sample = 104   #每轮训练总共训练的样本总数
    sft_data = load_sft_data(r"sample_data.json")
    ## 进行模型微调，
    for epoch in range( sft_epoch_num ):
        model.train()
        watch_loss = []
        for batch in range(int(sft_train_sample / batch_size)):
            x, y = build_sft_dataset(batch_size, vocab, window_size, title_size ,sft_data) #构建一组训练样本
            if torch.cuda.is_available():
                x, y = x.cuda(), y.cuda()
            optim.zero_grad()    #梯度归零
            loss = model(x, y, True)   #计算loss
            loss.backward()      #计算梯度
            optim.step()         #更新权重
            watch_loss.append(loss.item())
        print("=========\n第%d轮平均loss:%f" % (epoch + 1, np.mean(watch_loss)))
        print(generate_replay("直播预告：《我不是潘金莲》", model, vocab, window_size))
        print(generate_replay("女生注意：有人通过微信“招", model, vocab, window_size))

    if not save_weight:
        return
    else:
        base_name = os.path.basename(corpus_path).replace("txt", "pth")
        model_path = os.path.join("model", base_name)
        torch.save(model.state_dict(), model_path)
        return

def create_local_mask(seq_len, window_size):
    mask = torch.ones(seq_len, seq_len)
    for i in range(seq_len):
        mask[i, max(0, i-window_size):i+window_size+1] = 0  # 窗口内可见
    return mask

# 使用示例（同方案一）


if __name__ == "__main__":
    # build_vocab_from_corpus("corpus/all.txt")
    tokenizer = BertTokenizer.from_pretrained(r"E:\BaiduNetdiskDownload\八斗nlp\week6\bert-base-chinese\bert-base-chinese")
    train(tokenizer.vocab, r"corpus.txt", False)
    #result = create_local_mask(10, 5)
    #print(result)

