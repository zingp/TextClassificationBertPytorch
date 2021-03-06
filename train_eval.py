# coding: UTF-8
import os
import sys
BASEDIR = os.path.abspath(os.path.dirname(__file__))
sys.path.append(BASEDIR)
import time
import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F
from sklearn import metrics
from utils import time_diff, decode_to_word
from pytorch_pretrained.optimization import BertAdam


def train(config, model, train_iter, dev_iter, test_iter):
    start_time = time.time()
    model.train()
    param_optimizer = list(model.named_parameters())
    no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
    optimizer_grouped_parameters = [
        {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)], 'weight_decay': 0.01},
        {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}]
    # optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    optimizer = BertAdam(optimizer_grouped_parameters,
                         lr=config.learning_rate,
                         warmup=0.05,
                         t_total=len(train_iter) * config.num_epochs)
    total_batch, last_improve = 0, 0    # 记录进行到多少batch, 上次验证集loss下降的batch数
    dev_min_loss = float('inf')
    early_stop = False                  # 记录是否很久没有效果提升
    model.train()
    for epoch in range(config.num_epochs):
        print('Epoch [{}/{}]'.format(epoch + 1, config.num_epochs))
        for i, (input_ids, masks, labels) in enumerate(train_iter):
            outputs = model(input_ids, masks)
            model.zero_grad()
            loss = F.cross_entropy(outputs, labels)
            loss.backward()
            optimizer.step()
            if total_batch % 10 == 0:
                # 每多少轮输出在训练集和验证集上的效果
                true = labels.data.cpu()
                predic = torch.max(outputs.data, 1)[1].cpu()
                train_acc = metrics.accuracy_score(true, predic)
                dev_acc, dev_loss = evaluate(config, model, dev_iter)
                if dev_loss < dev_min_loss:
                    dev_min_loss = dev_loss
                    torch.save(model.state_dict(), config.save_path)
                    improve = '*'
                    last_improve = total_batch
                else:
                    improve = ''
                time_dif = time_diff(start_time)
                msg = 'Iter: {0:>6},  Train Loss: {1:>5.2},  Train Acc: {2:>6.2%},  Val Loss: {3:>5.2},  Val Acc: {4:>6.2%},  Time: {5} {6}'
                print(msg.format(total_batch, loss.item(), train_acc, dev_loss, dev_acc, time_dif, improve))
                model.train()
            total_batch += 1
            if total_batch - last_improve > config.require_improvement:
                # 验证集loss超过1000batch没下降，结束训练
                print("No optimization for a long time, auto-stopping...")
                early_stop = True
                break
        if early_stop:
            break
    test(config, model, test_iter, rate=0.5)


def test(config, model, data_iter, rate=0.5):
    # 把不安全的打印出来
    model.load_state_dict(torch.load(config.save_path))
    model.eval()
    start_time = time.time()
    loss_total = 0
    predict_all = np.array([], dtype=int)
    labels_all = np.array([], dtype=int)
    #unsafe_pred_err = []
    with torch.no_grad():
        for input_ids, masks, labels in data_iter:
            outputs = model(input_ids, masks)
            loss = F.cross_entropy(outputs, labels)
            loss_total += loss
            labels = labels.data.cpu().numpy()
            pred_softmax = F.softmax(outputs.data, dim=1)
            predic = (pred_softmax[::, 1] >= rate).cpu().numpy()
            for i, (y, p) in enumerate(zip(labels, predic)):
                if y == 1 and p == 0:
                    print(decode_to_word(config.tokenizer, input_ids[i]))
            labels_all = np.append(labels_all, labels)
            predict_all = np.append(predict_all, predic)

    test_acc = metrics.accuracy_score(labels_all, predict_all)
    test_loss = loss_total / len(data_iter)
    report = metrics.classification_report(labels_all, predict_all, target_names=config.class_list, digits=4)
    confusion = metrics.confusion_matrix(labels_all, predict_all)
    
    msg = 'Test Loss: {0:>5.2},  Test Acc: {1:>6.2%}'
    print(msg.format(test_loss, test_acc))
    print("Precision, Recall and F1-Score...")
    print(report)
    print("Confusion Matrix...")
    print(confusion)
    time_dif = time_diff(start_time)
    print("Time usage:", time_dif)


def evaluate(config, model, data_iter):
    model.eval()
    loss_total = 0
    predict_all = np.array([], dtype=int)
    labels_all = np.array([], dtype=int)
    with torch.no_grad():
        for input_ids, masks, labels in data_iter:
            outputs = model(input_ids, masks)
            loss = F.cross_entropy(outputs, labels)
            loss_total += loss
            labels = labels.data.cpu().numpy()
            predic = torch.max(outputs.data, 1)[1].cpu().numpy()
            labels_all = np.append(labels_all, labels)
            predict_all = np.append(predict_all, predic)

    acc = metrics.accuracy_score(labels_all, predict_all)
    return acc, loss_total / len(data_iter)

